from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CommunityMomentSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    moment_id: int = Field(..., description="ID của khoảnh khắc cộng đồng")
    status: str = Field(..., description="Trạng thái phê duyệt (PENDING)")
    created_at: datetime = Field(..., description="Thời gian tải ảnh lên")


class PublicCommunityMomentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    moment_id: int = Field(..., description="ID của khoảnh khắc")
    image_url: str = Field(..., description="URL ảnh hiển thị trên Hero (đã qua transformation responsive)")
    note: Optional[str] = Field(None, description="Lời nhắn khoảnh khắc (tối đa 80 ký tự, một dòng)")
    approved_at: Optional[datetime] = Field(None, description="Thời gian được duyệt")


class PublicHeroResponse(BaseModel):
    items: list[PublicCommunityMomentItem] = Field(
        default_factory=list,
        description="Danh sách tối đa 5 ảnh cộng đồng mới nhất đã được phê duyệt",
    )


class AdminCommunityMomentUploader(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int = Field(..., description="ID người dùng tải ảnh")
    full_name: str = Field(..., description="Tên người dùng")
    avatar_url: Optional[str] = Field(None, description="Ảnh đại diện người dùng")


class AdminCommunityMomentReviewer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int = Field(..., description="ID quản trị viên duyệt ảnh")
    full_name: str = Field(..., description="Tên quản trị viên")


class AdminCommunityMomentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    moment_id: int = Field(..., description="ID khoảnh khắc")
    image_url: str = Field(..., description="URL ảnh")
    thumbnail_url: Optional[str] = Field(None, description="URL ảnh thumbnail 200px")
    detail_image_url: Optional[str] = Field(None, description="URL ảnh chi tiết 800px")
    note: Optional[str] = Field(None, description="Lời nhắn gửi kèm ảnh của người dùng")
    status: str = Field(..., description="Trạng thái (PENDING, APPROVED, REJECTED)")
    created_at: datetime = Field(..., description="Thời gian tải lên")
    reviewed_at: Optional[datetime] = Field(None, description="Thời gian xét duyệt")
    uploader: AdminCommunityMomentUploader = Field(..., description="Thông tin người tải ảnh")
    reviewer: Optional[AdminCommunityMomentReviewer] = Field(None, description="Thông tin quản trị viên xét duyệt")


class AdminCommunityMomentCursorPage(BaseModel):
    items: list[AdminCommunityMomentItem] = Field(default_factory=list)
    next_cursor: Optional[str] = Field(None, description="Con trỏ phân trang tiếp theo")
    has_more: bool = Field(False, description="Còn dữ liệu trang kế tiếp không")


class CommunityMomentActionResponse(BaseModel):
    moment_id: int = Field(..., description="ID khoảnh khắc")
    status: str = Field(..., description="Trạng thái thao tác (REJECTED hoặc DELETED)")
    message: str = Field(..., description="Thông báo kết quả")
