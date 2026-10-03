from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.daily_needs.models import DailyNeed, DailyJournalCheckin
from app.modules.daily_needs.repository import get_vietnam_today, VN_TZ
from app.modules.users.models import User, UserRole, UserStatus


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_active_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_active_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email="user_a_daily@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        phone="0352866196",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        avatar_url="https://res.cloudinary.com/test/avatar_a.jpg",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email="user_b_daily@ptit.edu.vn",
        full_name="Trần Minh Anh",
        phone="0987654321",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        avatar_url="https://res.cloudinary.com/test/avatar_b.jpg",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_user_can_create_first_note_today(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Initial check: no note today
        res = await test_client.get("/api/v1/daily-needs/me/today")
        assert res.status_code == 200
        assert res.json() is None

        # Create note
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Cần mua giáo trình Giải tích 1"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["content"] == "Cần mua giáo trình Giải tích 1"
        assert data["note_date"] == str(get_vietnam_today())
        assert data["checkin_created"] is True
        assert data["author"]["public_id"] == str(user_a.public_id)
        assert data["author"]["full_name"] == "Nguyễn Khắc Thịnh"
        assert data["author"]["avatar_url"] == user_a.avatar_url

        # Check me/today now returns it
        res = await test_client.get("/api/v1/daily-needs/me/today")
        assert res.status_code == 200
        assert res.json()["daily_need_id"] == data["daily_need_id"]


@pytest.mark.asyncio
async def test_same_user_put_updates_existing_note_today(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Create first -> checkin_created is True
        res1 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Cần mua sách Java"},
        )
        assert res1.status_code == 200
        assert res1.json()["checkin_created"] is True
        id1 = res1.json()["daily_need_id"]

        # Edit same day -> checkin_created is False
        res2 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Cần mua sách Java hoặc Spring Boot"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["daily_need_id"] == id1  # Same row updated!
        assert data2["content"] == "Cần mua sách Java hoặc Spring Boot"
        assert data2["checkin_created"] is False



@pytest.mark.asyncio
async def test_reject_empty_or_whitespace_only(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Empty string
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": ""},
        )
        assert res.status_code == 422

        # Whitespace only
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "   \n\t  "},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_reject_exceeding_120_chars(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        long_content = "A" * 121
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": long_content},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_another_user_can_create_own_note_same_day(
    test_client: AsyncClient, user_a: User, user_b: User
):
    with auth_patch(user_a):
        res_a = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Note của user A"},
        )
        assert res_a.status_code == 200

    with auth_patch(user_b):
        res_b = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Note của user B"},
        )
        assert res_b.status_code == 200

    # Public list shows both notes
    res = await test_client.get("/api/v1/daily-needs/today")
    assert res.status_code == 200
    items = res.json()["items"]
    contents = [item["content"] for item in items]
    assert "Note của user A" in contents
    assert "Note của user B" in contents


@pytest.mark.asyncio
async def test_previous_day_note_does_not_block_today_note(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    yesterday = get_vietnam_today() - timedelta(days=1)
    old_note = DailyNeed(
        user_id=user_a.user_id,
        note_date=yesterday,
        content="Nhu cầu hôm qua",
        created_at=datetime.now(VN_TZ) - timedelta(days=1),
        updated_at=datetime.now(VN_TZ) - timedelta(days=1),
    )
    db_session.add(old_note)
    await db_session.commit()

    with auth_patch(user_a):
        # User A can still create today's note without conflict
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Nhu cầu hôm nay của user A"},
        )
        assert res.status_code == 200
        assert res.json()["note_date"] == str(get_vietnam_today())


@pytest.mark.asyncio
async def test_today_public_list_excludes_yesterday(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
):
    yesterday = get_vietnam_today() - timedelta(days=1)
    old_note = DailyNeed(
        user_id=user_a.user_id,
        note_date=yesterday,
        content="Note cũ từ hôm qua",
        created_at=datetime.now(VN_TZ) - timedelta(days=1),
        updated_at=datetime.now(VN_TZ) - timedelta(days=1),
    )
    db_session.add(old_note)

    today_note = DailyNeed(
        user_id=user_b.user_id,
        note_date=get_vietnam_today(),
        content="Note mới hôm nay",
        created_at=datetime.now(VN_TZ),
        updated_at=datetime.now(VN_TZ),
    )
    db_session.add(today_note)
    await db_session.commit()

    res = await test_client.get("/api/v1/daily-needs/today")
    assert res.status_code == 200
    items = res.json()["items"]
    contents = [item["content"] for item in items]
    assert "Note mới hôm nay" in contents
    assert "Note cũ từ hôm qua" not in contents


@pytest.mark.asyncio
async def test_delete_own_today_note(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Create
        await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Note cần xóa"},
        )

        # Delete
        del_res = await test_client.delete("/api/v1/daily-needs/me/today")
        assert del_res.status_code == 204

        # Verify it's gone
        check_res = await test_client.get("/api/v1/daily-needs/me/today")
        assert check_res.status_code == 200
        assert check_res.json() is None


@pytest.mark.asyncio
async def test_public_dto_does_not_expose_private_fields(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Kiểm tra bảo mật dữ liệu"},
        )

    res = await test_client.get("/api/v1/daily-needs/today")
    assert res.status_code == 200
    item = res.json()["items"][0]
    author = item["author"]

    # Allowed safe fields
    assert "public_id" in author
    assert "user_id" not in author
    assert "full_name" in author
    assert "avatar_url" in author

    # Strict check for private fields
    assert "email" not in author
    assert "phone" not in author
    assert "bank_account_number" not in author
    assert "bank_bin" not in author


@pytest.mark.asyncio
async def test_database_unique_constraint_enforced(
    db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    note1 = DailyNeed(
        user_id=user_a.user_id,
        note_date=today,
        content="Note 1",
    )
    db_session.add(note1)
    await db_session.commit()

    # Attempting to insert a direct second row with same user_id and note_date must raise IntegrityError
    note2 = DailyNeed(
        user_id=user_a.user_id,
        note_date=today,
        content="Note 2",
    )
    db_session.add(note2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_delete_when_no_note_today_returns_204(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Deleting when no note exists today still returns 204
        res = await test_client.delete("/api/v1/daily-needs/me/today")
        assert res.status_code == 204


@pytest.mark.asyncio
async def test_max_ten_notes_returned_and_recency_ordering(
    test_client: AsyncClient, db_session: AsyncSession
):
    today = get_vietnam_today()
    # Create 12 distinct users with notes today
    for i in range(12):
        u = User(
            email=f"multi_user_{i}@ptit.edu.vn",
            full_name=f"Sinh viên {i}",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        db_session.add(u)
        await db_session.flush()

        note = DailyNeed(
            user_id=u.user_id,
            note_date=today,
            content=f"Cần mua đồ #{i}",
            created_at=datetime.now(VN_TZ) + timedelta(minutes=i),
            updated_at=datetime.now(VN_TZ) + timedelta(minutes=i),
        )
        db_session.add(note)

    await db_session.commit()

    res = await test_client.get("/api/v1/daily-needs/today")
    assert res.status_code == 200
    items = res.json()["items"]
    # Enforce maximum 10
    assert len(items) == 10
    # Enforce recency ordering: the newest created (i=11) should be first
    assert items[0]["content"] == "Cần mua đồ #11"
    assert items[1]["content"] == "Cần mua đồ #10"
    assert items[9]["content"] == "Cần mua đồ #2"


@pytest.mark.asyncio
async def test_first_ever_journal_gives_streak_1_and_posted_today_true(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Before posting: streak = 0, has_posted_today = False
        summary_res = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res.status_code == 200
        data = summary_res.json()
        assert data["streak_count"] == 0
        assert data["has_posted_today"] is False
        assert data["today_journal"] is None

        # Post first journal today
        post_res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Hôm nay cần tìm giáo trình Giải tích"},
        )
        assert post_res.status_code == 200

        # After posting: streak = 1, has_posted_today = True
        summary_res2 = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res2.status_code == 200
        data2 = summary_res2.json()
        assert data2["streak_count"] == 1
        assert data2["has_posted_today"] is True
        assert data2["today_journal"] is not None
        assert data2["today_journal"]["content"] == "Hôm nay cần tìm giáo trình Giải tích"


@pytest.mark.asyncio
async def test_consecutive_days_streak_and_unposted_today_shows_yesterday_chain(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    # Populate past 4 consecutive days: today - 4, today - 3, today - 2, today - 1
    for day_offset in range(4, 0, -1):
        past_date = today - timedelta(days=day_offset)
        checkin = DailyJournalCheckin(
            user_id=user_a.user_id,
            checkin_date=past_date,
            created_at=datetime.now(VN_TZ) - timedelta(days=day_offset),
        )
        db_session.add(checkin)
    await db_session.commit()

    with auth_patch(user_a):
        # Before posting today: consecutive chain ending yesterday is 4
        # has_checked_in_today = False (gray flame in UI with 4)
        summary_res = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res.status_code == 200
        data = summary_res.json()
        assert data["streak_count"] == 4
        assert data["has_journal_today"] is False
        assert data["has_checked_in_today"] is False
        assert data["has_posted_today"] is False

        # Post today's journal
        post_res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Journal for today 5th consecutive day"},
        )
        assert post_res.status_code == 200
        assert post_res.json()["checkin_created"] is True

        # After posting today: streak becomes 5, has_checked_in_today = True (active flame)
        summary_res2 = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res2.status_code == 200
        data2 = summary_res2.json()
        assert data2["streak_count"] == 5
        assert data2["has_journal_today"] is True
        assert data2["has_checked_in_today"] is True
        assert data2["has_posted_today"] is True


@pytest.mark.asyncio
async def test_streak_longer_than_365_days_does_not_truncate(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    # Populate 370 consecutive days up to today
    for day_offset in range(369, -1, -1):
        d = today - timedelta(days=day_offset)
        checkin = DailyJournalCheckin(
            user_id=user_a.user_id,
            checkin_date=d,
            created_at=datetime.now(VN_TZ) - timedelta(days=day_offset),
        )
        db_session.add(checkin)
    await db_session.commit()

    with auth_patch(user_a):
        summary_res = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res.status_code == 200
        data = summary_res.json()
        # Exactly 370 days - no arbitrary 365 cap!
        assert data["streak_count"] == 370
        assert data["has_checked_in_today"] is True
        assert data["has_posted_today"] is True


@pytest.mark.asyncio
async def test_same_day_edit_does_not_increment_streak(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Post first version
        res1 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Bản đầu tiên trong ngày"},
        )
        assert res1.json()["checkin_created"] is True

        s1 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s1["streak_count"] == 1
        assert s1["has_checked_in_today"] is True
        assert s1["has_journal_today"] is True

        # Edit same day -> checkin_created is False
        res2 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Bản chỉnh sửa trong ngày"},
        )
        assert res2.json()["checkin_created"] is False

        s2 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s2["streak_count"] == 1
        assert s2["has_checked_in_today"] is True
        assert s2["has_journal_today"] is True
        assert s2["today_journal"]["content"] == "Bản chỉnh sửa trong ngày"


@pytest.mark.asyncio
async def test_missed_day_breaks_streak(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    # User posted on today - 3 and today - 2, but SKIPPED yesterday (today - 1)
    for day_offset in [3, 2]:
        past_date = today - timedelta(days=day_offset)
        checkin = DailyJournalCheckin(
            user_id=user_a.user_id,
            checkin_date=past_date,
            created_at=datetime.now(VN_TZ) - timedelta(days=day_offset),
        )
        db_session.add(checkin)
    await db_session.commit()

    with auth_patch(user_a):
        # Before posting today: yesterday was skipped, so streak is 0
        summary_res = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res.status_code == 200
        data = summary_res.json()
        assert data["streak_count"] == 0
        assert data["has_checked_in_today"] is False
        assert data["has_journal_today"] is False

        # Post today
        await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Bắt đầu chuỗi mới hôm nay"},
        )
        summary_res2 = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res2.status_code == 200
        data2 = summary_res2.json()
        # New streak starts at 1, not 3!
        assert data2["streak_count"] == 1
        assert data2["has_checked_in_today"] is True
        assert data2["has_journal_today"] is True


@pytest.mark.asyncio
async def test_delete_today_journal_preserves_checkin_and_streak(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    # Consecutive 3 days ending yesterday
    for day_offset in range(3, 0, -1):
        past_date = today - timedelta(days=day_offset)
        checkin = DailyJournalCheckin(
            user_id=user_a.user_id,
            checkin_date=past_date,
            created_at=datetime.now(VN_TZ) - timedelta(days=day_offset),
        )
        db_session.add(checkin)
    await db_session.commit()

    with auth_patch(user_a):
        # Post today -> streak becomes 4
        res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Day 4 note"},
        )
        assert res.json()["checkin_created"] is True
        s1 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s1["streak_count"] == 4
        assert s1["has_journal_today"] is True
        assert s1["has_checked_in_today"] is True
        assert s1["has_posted_today"] is True

        # Delete today's note content
        del_res = await test_client.delete("/api/v1/daily-needs/me/today")
        assert del_res.status_code == 204

        # CRITICAL DOMAIN BEHAVIOR:
        # Content is deleted (today_journal=None, has_journal_today=False)
        # BUT check-in is preserved: has_checked_in_today=True, streak_count remains 4, flame active!
        s2 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s2["streak_count"] == 4  # Unchanged!
        assert s2["has_journal_today"] is False
        assert s2["has_checked_in_today"] is True
        assert s2["has_posted_today"] is True
        assert s2["today_journal"] is None

        # Content is removed from public endpoints
        pub_list = (await test_client.get("/api/v1/daily-needs/today")).json()["items"]
        assert not any(item["author"]["public_id"] == str(user_a.public_id) for item in pub_list)

        pub_user = (await test_client.get(f"/api/v1/daily-needs/users/{user_a.public_id}/today")).json()
        assert pub_user is None


@pytest.mark.asyncio
async def test_delete_today_when_yesterday_was_missed_preserves_streak_and_flame(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # Post first journal today (yesterday was empty)
        await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Solo note today"},
        )
        s1 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s1["streak_count"] == 1
        assert s1["has_journal_today"] is True
        assert s1["has_checked_in_today"] is True

        # Delete today's note
        await test_client.delete("/api/v1/daily-needs/me/today")

        # Recalculated: streak STILL 1, has_checked_in_today STILL True!
        s2 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s2["streak_count"] == 1
        assert s2["has_journal_today"] is False
        assert s2["has_checked_in_today"] is True
        assert s2["today_journal"] is None


@pytest.mark.asyncio
async def test_repost_after_delete_reuses_checkin_and_does_not_increment_streak(
    test_client: AsyncClient, user_a: User
):
    with auth_patch(user_a):
        # 1. First publish
        res1 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Lần đăng 1"},
        )
        assert res1.json()["checkin_created"] is True
        s1 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s1["streak_count"] == 1

        # 2. Delete
        await test_client.delete("/api/v1/daily-needs/me/today")
        s2 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s2["streak_count"] == 1
        assert s2["has_journal_today"] is False
        assert s2["has_checked_in_today"] is True

        # 3. Repost after delete -> checkin_created is False, streak unchanged!
        res3 = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Lần đăng 2 sau khi xóa"},
        )
        assert res3.status_code == 200
        assert res3.json()["checkin_created"] is False  # Server truth: no new checkin!
        s3 = (await test_client.get("/api/v1/daily-needs/me/summary")).json()
        assert s3["streak_count"] == 1  # Not 2!
        assert s3["has_journal_today"] is True
        assert s3["has_checked_in_today"] is True
        assert s3["today_journal"]["content"] == "Lần đăng 2 sau khi xóa"


@pytest.mark.asyncio
async def test_concurrent_first_publishes_create_exactly_one_checkin(
    mock_redis_conn
):
    import asyncio
    from sqlalchemy import text
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.core.database import SessionLocal, get_db
    from app.core.redis import get_redis

    # Create committed test user for real concurrent connection testing
    async with SessionLocal() as s:
        user_res = await s.execute(
            text("""
                INSERT INTO users (email, full_name, role, status)
                VALUES ('concurrent_user_checkin@ptit.edu.vn', 'Concurrent User', 'STUDENT', 'ACTIVE')
                RETURNING user_id;
            """)
        )
        test_user_id = user_res.scalar_one()
        await s.commit()

    test_user = User(
        user_id=test_user_id,
        email="concurrent_user_checkin@ptit.edu.vn",
        full_name="Concurrent User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )


    async def get_test_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn

    today = get_vietnam_today()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with auth_patch(test_user):
                tasks = [
                    client.put("/api/v1/daily-needs/me/today", json={"content": f"Concurrent note {i}"})
                    for i in range(2)
                ]
                res1, res2 = await asyncio.gather(*tasks)

                assert res1.status_code == 200
                assert res2.status_code == 200

                # Exactly one request reports checkin_created = True, the other reports False
                created_flags = [res1.json()["checkin_created"], res2.json()["checkin_created"]]
                assert created_flags.count(True) == 1
                assert created_flags.count(False) == 1

                async with SessionLocal() as s:
                    r = await s.execute(
                        text("SELECT count(*) FROM daily_journal_checkins WHERE user_id = :uid AND checkin_date = :dt"),
                        {"uid": test_user_id, "dt": today},
                    )
                    assert r.scalar() == 1
    finally:
        # Cleanup rows created by direct session for test_user
        async with SessionLocal() as s:
            await s.execute(text("DELETE FROM daily_journal_checkins WHERE user_id = :uid"), {"uid": test_user_id})
            await s.execute(text("DELETE FROM daily_needs WHERE user_id = :uid"), {"uid": test_user_id})
            await s.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": test_user_id})
            await s.commit()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)




@pytest.mark.asyncio
async def test_unique_constraint_prevents_duplicate_user_date_checkins(
    db_session: AsyncSession, user_a: User
):
    today = get_vietnam_today()
    c1 = DailyJournalCheckin(user_id=user_a.user_id, checkin_date=today)
    db_session.add(c1)
    await db_session.flush()

    c2 = DailyJournalCheckin(user_id=user_a.user_id, checkin_date=today)
    db_session.add(c2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()



@pytest.mark.asyncio
async def test_public_user_today_journal_dto_and_safety(
    test_client: AsyncClient, user_a: User, user_b: User
):
    with auth_patch(user_a):
        await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Đang tìm giáo trình Giải tích để học tối nay"},
        )

    # User B requests User A's public today journal
    with auth_patch(user_b):
        res = await test_client.get(f"/api/v1/daily-needs/users/{user_a.public_id}/today")
        assert res.status_code == 200
        data = res.json()
        assert data is not None
        assert data["content"] == "Đang tìm giáo trình Giải tích để học tối nay"
        assert data["note_date"] == str(get_vietnam_today())
        assert "daily_need_id" in data
        assert "updated_at" in data

        # Author safe fields only
        author = data["author"]
        assert author["public_id"] == str(user_a.public_id)
        assert "user_id" not in author
        assert author["full_name"] == user_a.full_name
        assert author["avatar_url"] == user_a.avatar_url

        # Ensure NO private fields leaked
        assert "email" not in data
        assert "phone" not in data
        assert "email" not in author
        assert "phone" not in author
        assert "bank_account_number" not in author
        assert "bank_bin" not in author


@pytest.mark.asyncio
async def test_public_user_today_journal_returns_null_when_no_post_today(
    test_client: AsyncClient, user_a: User
):
    # User A has no note today
    res = await test_client.get(f"/api/v1/daily-needs/users/{user_a.public_id}/today")
    assert res.status_code == 200
    assert res.json() is None


@pytest.mark.asyncio
async def test_public_user_today_journal_does_not_return_yesterdays_post(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    yesterday = get_vietnam_today() - timedelta(days=1)
    old_note = DailyNeed(
        user_id=user_a.user_id,
        note_date=yesterday,
        content="Note cũ hôm qua",
        created_at=datetime.now(VN_TZ) - timedelta(days=1),
        updated_at=datetime.now(VN_TZ) - timedelta(days=1),
    )
    db_session.add(old_note)
    await db_session.commit()

    # User A has only yesterday's note, no note today
    res = await test_client.get(f"/api/v1/daily-needs/users/{user_a.public_id}/today")
    assert res.status_code == 200
    assert res.json() is None


@pytest.mark.asyncio
async def test_recent_daily_needs_empty(test_client: AsyncClient, db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM daily_needs"))
    await db_session.flush()
    res = await test_client.get("/api/v1/daily-needs/recent")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert data["items"] == []


@pytest.mark.asyncio
async def test_recent_daily_needs_returns_historical_across_dates(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    await db_session.execute(text("DELETE FROM daily_needs"))
    await db_session.flush()
    yesterday = get_vietnam_today() - timedelta(days=1)
    old_note = DailyNeed(
        user_id=user_a.user_id,
        note_date=yesterday,
        content="Nhật ký hôm qua rất vui",
        created_at=datetime.now(VN_TZ) - timedelta(days=1),
        updated_at=datetime.now(VN_TZ) - timedelta(days=1),
    )
    db_session.add(old_note)
    await db_session.flush()

    # /today returns empty because there is 0 note today
    today_res = await test_client.get("/api/v1/daily-needs/today")
    assert today_res.status_code == 200
    assert today_res.json()["items"] == []

    # /recent returns the yesterday note across dates!
    recent_res = await test_client.get("/api/v1/daily-needs/recent")
    assert recent_res.status_code == 200
    items = recent_res.json()["items"]
    assert len(items) == 1
    assert items[0]["daily_need_id"] == old_note.daily_need_id
    assert items[0]["content"] == "Nhật ký hôm qua rất vui"
    assert items[0]["author"]["public_id"] == str(user_a.public_id)


@pytest.mark.asyncio
async def test_recent_daily_needs_caps_at_10_and_ordered_deterministically(
    test_client: AsyncClient, db_session: AsyncSession
):
    await db_session.execute(text("DELETE FROM daily_needs"))
    await db_session.flush()
    # Create 12 users with 12 journals across dates
    users = []
    for i in range(12):
        u = User(
            email=f"user_recent_{i}@ptit.edu.vn",
            full_name=f"User Recent {i}",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        users.append(u)
    db_session.add_all(users)
    await db_session.flush()

    today = get_vietnam_today()
    notes = []
    for i, u in enumerate(users):
        n_date = today - timedelta(days=i)
        note = DailyNeed(
            user_id=u.user_id,
            note_date=n_date,
            content=f"Journal day {i}",
            created_at=datetime.now(VN_TZ) - timedelta(days=i),
            updated_at=datetime.now(VN_TZ) - timedelta(days=i),
        )
        notes.append(note)
    db_session.add_all(notes)
    await db_session.flush()

    res = await test_client.get("/api/v1/daily-needs/recent")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]
    assert len(items) == 10
    dates = [item["note_date"] for item in items]
    assert dates == sorted(dates, reverse=True)
    returned_ids = [item["daily_need_id"] for item in items]
    assert len(returned_ids) == len(set(returned_ids))


@pytest.mark.asyncio
async def test_delete_today_journal_preserves_streak_and_recent_feed_falls_back(
    test_client: AsyncClient, db_session: AsyncSession, user_a: User
):
    await db_session.execute(text("DELETE FROM daily_needs"))
    await db_session.flush()
    yesterday = get_vietnam_today() - timedelta(days=1)
    hist_note = DailyNeed(
        user_id=user_a.user_id,
        note_date=yesterday,
        content="Hôm qua chăm chỉ",
        created_at=datetime.now(VN_TZ) - timedelta(days=1),
        updated_at=datetime.now(VN_TZ) - timedelta(days=1),
    )
    db_session.add(hist_note)
    await db_session.flush()

    with auth_patch(user_a):
        put_res = await test_client.put(
            "/api/v1/daily-needs/me/today",
            json={"content": "Hôm nay vui vẻ"},
        )
        assert put_res.status_code == 200

        summary_res = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_res.status_code == 200
        streak_before_delete = summary_res.json()["streak_count"]
        assert streak_before_delete >= 1

        del_res = await test_client.delete("/api/v1/daily-needs/me/today")
        assert del_res.status_code == 204

        summary_after = await test_client.get("/api/v1/daily-needs/me/summary")
        assert summary_after.status_code == 200
        assert summary_after.json()["streak_count"] == streak_before_delete
        assert summary_after.json()["has_checked_in_today"] is True

        recent_res = await test_client.get("/api/v1/daily-needs/recent")
        assert recent_res.status_code == 200
        items = recent_res.json()["items"]
        assert len(items) == 1
        assert items[0]["daily_need_id"] == hist_note.daily_need_id
        assert items[0]["content"] == "Hôm qua chăm chỉ"
