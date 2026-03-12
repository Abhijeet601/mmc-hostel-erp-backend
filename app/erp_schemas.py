from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StudentRegistrationRequest(BaseModel):
    email: str
    date_of_birth: date
    mobile_number: str
    password: str | None = None


class StudentRegistrationResponse(BaseModel):
    application_number: str
    email: str
    mobile_number: str
    password: str
    message: str


class StudentLoginRequest(BaseModel):
    email: str
    password: str
    date_of_birth: date | None = None
    dob: date | None = None


class StudentLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    application_completed: bool
    redirect: str
    application_number: str
    student_name: str | None = None


class StatusTrackerStep(BaseModel):
    key: str
    label: str
    state: str
    date: datetime | None = None
    description: str


class ReceiptSummary(BaseModel):
    payment_type: str
    amount: float
    transaction_id: str
    payment_date: datetime
    receipt_url: str | None = None


class ApplicationFormPayload(BaseModel):
    application_number: str
    email: str
    mobile_number: str
    registration_date_of_birth: date
    form_status: str
    is_editable: bool
    data: dict[str, object | None]


class StudentDashboardResponse(BaseModel):
    application_number: str
    student_name: str | None = None
    email: str
    mobile_number: str
    application_status: str
    form_status: str
    verification_status: str
    application_payment_status: str
    shortlist_status: str
    hostel_status: str
    shortlisted: bool
    can_edit_application: bool
    can_pay_application_fee: bool
    can_choose_hostel: bool
    can_pay_hostel_fee: bool
    preferred_hostel: str | None = None
    allocated_hostel: str | None = None
    application_fee_amount: int
    hostel_fee_amount: int | None = None
    photo_url: str | None = None
    application_receipt: ReceiptSummary | None = None
    hostel_receipt: ReceiptSummary | None = None
    tracker: list[StatusTrackerStep]
    summary: dict[str, object | None]


class AdminStudentDetailResponse(StudentDashboardResponse):
    id: int
    registration_date_of_birth: date
    registered_at: datetime
    application_submitted_at: datetime | None = None
    verified_at: datetime | None = None
    shortlisted_at: datetime | None = None
    hostel_allocated_at: datetime | None = None


class GenericMessageResponse(BaseModel):
    message: str


class PaymentResponse(BaseModel):
    message: str
    transaction_id: str
    receipt_url: str | None = None
    email_status: str
    amount: float


class ERPStudentSummary(BaseModel):
    id: int
    application_number: str
    name: str | None = None
    email: str
    mobile_number: str
    course_name: str | None = None
    category: str | None = None
    session: str | None = None
    program: str | None = None
    form_status: str
    verification_status: str
    application_payment_status: str
    shortlist_status: str
    hostel_status: str
    preferred_hostel: str | None = None
    allocated_hostel: str | None = None
    application_submitted_at: datetime | None = None
    verified_at: datetime | None = None
    shortlisted_at: datetime | None = None
    hostel_payment_date: datetime | None = None


class AdminStudentListResponse(BaseModel):
    total: int
    items: list[ERPStudentSummary]


class ChartDatum(BaseModel):
    label: str
    value: int


class AdminDashboardResponse(BaseModel):
    total_applications: int
    total_paid: int
    pending_applications: int
    shortlisted_students: int
    verified_students: int
    hostel_allocated_students: int
    hostel_paid_students: int
    application_revenue: float
    hostel_revenue: float
    by_course: list[ChartDatum]
    by_category: list[ChartDatum]
    by_status: list[ChartDatum]
    by_hostel: list[ChartDatum]


class AdminVerifyRequest(BaseModel):
    verified: bool = True


class AdminShortlistRequest(BaseModel):
    shortlisted: bool = True


class AdminAllocationRequest(BaseModel):
    hostel_name: str


class ShortlistUploadResponse(BaseModel):
    message: str
    marked_shortlisted: int
    allocated_hostel_count: int = 0
    allocated_hostel_name: str | None = None
    ignored_rows: int
    total_rows: int


class ReceiptSummaryModel(BaseModel):
    payment_type: str
    amount: float
    transaction_id: str
    payment_date: datetime
    receipt_url: str | None = None

    model_config = ConfigDict(from_attributes=True)
