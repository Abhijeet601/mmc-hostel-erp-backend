from enum import Enum


class GenderEnum(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"


class CategoryEnum(str, Enum):
    UR = "UR"
    EWS = "EWS"
    BC = "BC"
    EBC = "EBC"
    SC = "SC"
    ST = "ST"


class ReligionEnum(str, Enum):
    HINDU = "Hindu"
    MUSLIM = "Muslim"
    SIKH = "Sikh"
    CHRISTIAN = "Christian"
    OTHER = "Other"


class CourseEnum(str, Enum):
    BA = "BA"
    BSC = "BSc"
    BCOM = "BCom"
    BSW = "BSW"
    BCA = "BCA"
    BBA = "BBA"


class SessionEnum(str, Enum):
    S2026_30 = "2026-30"
    S2026_29 = "2026-29"
    S2025_28 = "2025-28"
    S2024_27 = "2024-27"


class ProgramEnum(str, Enum):
    UG = "UG"
    PG = "PG"


class PGCourseEnum(str, Enum):
    MSC_CHEMISTRY = "MSc Chemistry"
    MA_ECONOMICS = "MA Economics"
    MA_PSYCHOLOGY = "MA Psychology"


class ApplicationStatusEnum(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APP_PAYMENT_PENDING = "application_payment_pending"
    APP_PAYMENT_DONE = "application_payment_done"
    SHORTLISTED = "shortlisted"
    NOT_SHORTLISTED = "not_shortlisted"
    HOSTEL_PAYMENT_PENDING = "hostel_payment_pending"
    HOSTEL_PAYMENT_DONE = "hostel_payment_done"


class HostelTypeEnum(str, Enum):
    VAIDEHI = "Vaidehi Hostel"
    MAHIMA = "Mahima Hostel"
