"""
Vietnamese Bank Registry for NAPAS / VietQR Compatibility.

Source: NAPAS / VietQR.io Supported Bank List (Updated: 2026-08).
VietQR is a standard/trademark of NAPAS.
VietQR.io provides developer tools and Quick Link generation compatible with VietQR.
The canonical identifier stored in PostgreSQL is the 6-digit (or up to 8-digit) Bank BIN.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class BankInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bin: str
    code: str
    short_name: str
    name: str


# Static normalized bank registry
SUPPORTED_BANKS: List[BankInfo] = [
    BankInfo(bin="970436", code="VCB", short_name="Vietcombank", name="Ngân hàng TMCP Ngoại Thương Việt Nam"),
    BankInfo(bin="970415", code="CTG", short_name="VietinBank", name="Ngân hàng TMCP Công thương Việt Nam"),
    BankInfo(bin="970418", code="BIDV", short_name="BIDV", name="Ngân hàng TMCP Đầu tư và Phát triển Việt Nam"),
    BankInfo(bin="970405", code="VBA", short_name="Agribank", name="Ngân hàng Nông nghiệp và Phát triển Nông thôn Việt Nam"),
    BankInfo(bin="970422", code="MB", short_name="MBBank", name="Ngân hàng TMCP Quân đội"),
    BankInfo(bin="970407", code="TCB", short_name="Techcombank", name="Ngân hàng TMCP Kỹ thương Việt Nam"),
    BankInfo(bin="970416", code="ACB", short_name="ACB", name="Ngân hàng TMCP Á Châu"),
    BankInfo(bin="970432", code="VPB", short_name="VPBank", name="Ngân hàng TMCP Việt Nam Thịnh Vượng"),
    BankInfo(bin="970423", code="TPB", short_name="TPBank", name="Ngân hàng TMCP Tiên Phong"),
    BankInfo(bin="970403", code="STB", short_name="Sacombank", name="Ngân hàng TMCP Sài Gòn Thương Tín"),
    BankInfo(bin="970437", code="HDB", short_name="HDBank", name="Ngân hàng TMCP Phát triển TP.HCM"),
    BankInfo(bin="970441", code="VIB", short_name="VIB", name="Ngân hàng TMCP Quốc tế Việt Nam"),
    BankInfo(bin="970443", code="SHB", short_name="SHB", name="Ngân hàng TMCP Sài Gòn - Hà Nội"),
    BankInfo(bin="970440", code="SSB", short_name="SeABank", name="Ngân hàng TMCP Đông Nam Á"),
    BankInfo(bin="970426", code="MSB", short_name="MSB", name="Ngân hàng TMCP Hàng Hải Việt Nam"),
    BankInfo(bin="970448", code="OCB", short_name="OCB", name="Ngân hàng TMCP Phương Đông"),
    BankInfo(bin="970449", code="LPB", short_name="LPBank", name="Ngân hàng TMCP Lộc Phát Việt Nam"),
    BankInfo(bin="970409", code="BAB", short_name="BacABank", name="Ngân hàng TMCP Bắc Á"),
    BankInfo(bin="970412", code="PVB", short_name="PVcomBank", name="Ngân hàng TMCP Đại Chúng Việt Nam"),
    BankInfo(bin="970419", code="NCB", short_name="NCB", name="Ngân hàng TMCP Quốc Dân"),
    BankInfo(bin="970424", code="SHBVN", short_name="ShinhanBank", name="Ngân hàng TNHH MTV Shinhan Việt Nam"),
    BankInfo(bin="970429", code="SCB", short_name="SCB", name="Ngân hàng TMCP Sài Gòn"),
    BankInfo(bin="970430", code="PGB", short_name="PGBank", name="Ngân hàng TMCP Thịnh vượng và Phát triển"),
    BankInfo(bin="970427", code="VAB", short_name="VietABank", name="Ngân hàng TMCP Việt Á"),
    BankInfo(bin="970428", code="NAB", short_name="NamABank", name="Ngân hàng TMCP Nam Á"),
    BankInfo(bin="970452", code="KLB", short_name="KienLongBank", name="Ngân hàng TMCP Kiên Long"),
    BankInfo(bin="970438", code="BVB", short_name="BaoVietBank", name="Ngân hàng TMCP Bảo Việt"),
    BankInfo(bin="970400", code="SGB", short_name="SaigonBank", name="Ngân hàng TMCP Sài Gòn Công Thương"),
    BankInfo(bin="970454", code="BVBANK", short_name="BVBank", name="Ngân hàng TMCP Bản Việt"),
    BankInfo(bin="970433", code="VBB", short_name="VietBank", name="Ngân hàng TMCP Việt Nam Thương Tín"),
    BankInfo(bin="970444", code="CBB", short_name="CBBank", name="Ngân hàng Thương mại TNHH MTV Xây dựng Việt Nam"),
    BankInfo(bin="970414", code="OJB", short_name="OceanBank", name="Ngân hàng Thương mại TNHH MTV Đại Dương"),
    BankInfo(bin="970408", code="GPB", short_name="GPBank", name="Ngân hàng Thương mại TNHH MTV Dầu Khí Toàn Cầu"),
    BankInfo(bin="970457", code="WVN", short_name="WooriBank", name="Ngân hàng TNHH MTV Woori Việt Nam"),
    BankInfo(bin="970421", code="VRB", short_name="VRB", name="Ngân hàng Liên doanh Việt - Nga"),
    BankInfo(bin="970439", code="PBVN", short_name="PublicBank", name="Ngân hàng TNHH MTV Public Việt Nam"),
    BankInfo(bin="970442", code="HLBVN", short_name="HongLeong", name="Ngân hàng TNHH MTV Hong Leong Việt Nam"),
    BankInfo(bin="970455", code="IBKHN", short_name="IBK - Hanoi", name="Ngân hàng Công nghiệp Hàn Quốc - Chi nhánh Hà Nội"),
    BankInfo(bin="970456", code="IBKHCM", short_name="IBK - HCM", name="Ngân hàng Công nghiệp Hàn Quốc - Chi nhánh TP.HCM"),
    BankInfo(bin="801011", code="NHB", short_name="Nonghyup Bank", name="Ngân hàng Nonghyup - Chi nhánh Hà Nội"),
    BankInfo(bin="668888", code="KBANK", short_name="KBank", name="Ngân hàng Kasikornbank - Chi nhánh TP.HCM"),
    BankInfo(bin="546034", code="CAKE", short_name="CAKE by VPBank", name="Ngân hàng số CAKE by VPBank"),
    BankInfo(bin="963388", code="TIMO", short_name="Timo by BanVietBank", name="Ngân hàng số Timo by BanVietBank"),
    BankInfo(bin="971005", code="VTLMONEY", short_name="Viettel Money", name="Tổng Công ty Dịch vụ Số Viettel"),
    BankInfo(bin="971011", code="VNPTMONEY", short_name="VNPT Money", name="Tập đoàn Bưu chính Viễn thông Việt Nam"),
]

# Fast lookup dictionaries
BANKS_BY_BIN: Dict[str, BankInfo] = {bank.bin: bank for bank in SUPPORTED_BANKS}
BANKS_BY_CODE: Dict[str, BankInfo] = {bank.code.upper(): bank for bank in SUPPORTED_BANKS}


def get_bank_by_bin(bin_code: str) -> Optional[BankInfo]:
    """Lookup BankInfo by canonical BIN."""
    if not bin_code:
        return None
    return BANKS_BY_BIN.get(bin_code.strip())


def get_bank_by_code(code: str) -> Optional[BankInfo]:
    """Lookup BankInfo by bank code alias."""
    if not code:
        return None
    return BANKS_BY_CODE.get(code.strip().upper())


def resolve_bank_bin(identifier: str) -> Optional[str]:
    """
    Resolve canonical bank BIN from either a BIN string or a bank code.
    Returns canonical BIN if valid, else None.
    """
    if not identifier:
        return None
    clean_id = identifier.strip()
    if clean_id in BANKS_BY_BIN:
        return clean_id
    upper_code = clean_id.upper()
    if upper_code in BANKS_BY_CODE:
        return BANKS_BY_CODE[upper_code].bin
    return None
