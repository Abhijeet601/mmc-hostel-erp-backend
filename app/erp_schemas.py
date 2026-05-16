from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


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


class StudentPasswordResetRequest(BaseModel):
    identifier: str
    date_of_birth: date
    mobile_number: str
    new_password: str


class StatusTrackerStep(BaseModel):
    key: str
    label: str
    state: str
    date: datetime | None = None
    description: str


class NotificationItem(BaseModel):
    title: str
    description: str
    tone: str = "info"
    created_at: datetime | None = None


class ReceiptSummary(BaseModel):
    payment_type: str
    amount: float
    transaction_id: str
    payment_date: datetime
    receipt_url: str | None = None


class ApplicationFormPayload(BaseModel):
    application_number: str
    application_type: str = "new"
    cycle_reference: str | None = None
    renewal_reference_number: str | None = None
    previous_application_number: str | None = None
    email: str
    mobile_number: str
    registration_date_of_birth: date
    form_status: str
    is_editable: bool
    data: dict[str, object | None]


class StudentDashboardResponse(BaseModel):
    application_number: str
    application_type: str = "new"
    cycle_reference: str | None = None
    renewal_reference_number: str | None = None
    can_start_renewal: bool = False
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
    allotted_category: str | None = None
    hostel_block: str | None = None
    room_number: str | None = None
    bed_number: str | None = None
    application_fee_amount: int
    hostel_fee_amount: int | None = None
    photo_url: str | None = None
    application_receipt: ReceiptSummary | None = None
    hostel_receipt: ReceiptSummary | None = None
    tracker: list[StatusTrackerStep]
    notifications: list[NotificationItem] = []
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
    payment_id: int
    payment_reference: str
    status: str
    transaction_id: str
    receipt_url: str | None = None
    email_status: str
    amount: float


class ComplaintCreateRequest(BaseModel):
    subject: str
    category: str
    description: str


class ComplaintUpdateRequest(BaseModel):
    status: str
    resolution_note: str | None = None


class ComplaintResponse(BaseModel):
    id: int
    ticket_number: str
    subject: str
    category: str
    description: str
    status: str
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ComplaintListResponse(BaseModel):
    total: int
    items: list[ComplaintResponse]


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
    allotted_category: str | None = None
    hostel_block: str | None = None
    room_number: str | None = None
    bed_number: str | None = None
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


class RecentActivity(BaseModel):
    title: str
    description: str
    timestamp: datetime | None = None
    tone: str = "info"


class AdminDashboardResponse(BaseModel):
    total_applications: int
    total_paid: int
    pending_applications: int
    shortlisted_students: int
    verified_students: int
    hostel_allocated_students: int
    hostel_paid_students: int
    old_students: int = 0
    total_rooms: int = 0
    occupied_beds: int = 0
    available_beds: int = 0
    application_revenue: float
    hostel_revenue: float
    by_course: list[ChartDatum]
    by_category: list[ChartDatum]
    by_status: list[ChartDatum]
    by_hostel: list[ChartDatum]
    recent_activities: list[RecentActivity] = []


class AdminVerifyRequest(BaseModel):
    verified: bool = True


class AdminShortlistRequest(BaseModel):
    shortlisted: bool = True


class AdminAllocationRequest(BaseModel):
    hostel_name: str | None = None
    room_id: int | None = None
    bed_number: str | None = None


class AdminPaymentSummary(BaseModel):
    id: str
    payment_id: int
    payment_type: str
    status: str
    payment_mode: str
    transaction_id: str
    amount: float
    payment_date: datetime
    receipt_url: str | None = None
    application_number: str
    student_id: int
    student_name: str | None = None
    course_name: str | None = None
    hostel_name: str | None = None


class AdminPaymentListResponse(BaseModel):
    total: int
    items: list[AdminPaymentSummary]


class HostelRoomSummary(BaseModel):
    id: int
    hostel_name: str
    block_name: str
    room_number: str
    bed_capacity: int
    occupied_beds: int
    available_beds: int
    is_active: bool
    notes: str | None = None


class HostelRoomListResponse(BaseModel):
    total: int
    items: list[HostelRoomSummary]


class AdminHostelRoomPayload(BaseModel):
    hostel_name: str
    block_name: str
    room_number: str
    bed_capacity: int
    is_active: bool = True
    notes: str | None = None


class ShortlistUploadResponse(BaseModel):
    message: str
    marked_shortlisted: int
    allocated_hostel_count: int = 0
    allocated_hostel_name: str | None = None
    ignored_rows: int
    total_rows: int


class BulkShortlistUploadResponse(BaseModel):
    message: str
    processed_rows: int
    shortlisted_yes: int
    shortlisted_no: int
    updated_allotted_category: int
    invalid_registrations: int = 0
    skipped_rows: int = 0


class BulkAllocationUploadResponse(BaseModel):
    message: str
    processed_rows: int
    allocated: int
    auto_assigned_beds: int = 0
    invalid_registrations: int = 0
    not_shortlisted: int = 0
    room_errors: int = 0
    skipped_rows: int = 0


class BulkCombinedUploadResponse(BaseModel):
    message: str
    processed_rows: int
    shortlisted_yes: int
    shortlisted_no: int
    updated_allotted_category: int
    allocated: int
    auto_assigned_beds: int = 0
    invalid_registrations: int = 0
    not_shortlisted: int = 0
    room_errors: int = 0
    skipped_rows: int = 0
    created: int = 0
    updated: int = 0
    generated_ids: int = 0
    error_report_url: str | None = None


class BulkOldStudentIdPreview(BaseModel):
    last_id: str | None = None
    next_ids: list[str] = Field(default_factory=list)
    generated_count: int = 0


class BulkOldStudentRowResult(BaseModel):
    row_number: int
    action: str
    matched_by: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    generated_hostel_id: bool = False
    allocation_updated: bool = False
    messages: list[str] = Field(default_factory=list)
    current_values: dict[str, str | None] = Field(default_factory=dict)
    proposed_values: dict[str, str | None] = Field(default_factory=dict)


class BulkUpsertOldStudentsResponse(BaseModel):
    mode: str
    message: str
    total: int
    created: int
    updated: int
    errors: int
    success_count: int
    update_count: int
    error_count: int
    generated_ids: int = 0
    allocated: int = 0
    error_rows: list[dict[str, object | None]] = Field(default_factory=list)
    error_details: list[dict[str, object | None]] = Field(default_factory=list)
    rows: list[BulkOldStudentRowResult] = Field(default_factory=list)
    hostel_id_preview: BulkOldStudentIdPreview | None = None
    error_report_url: str | None = None


class ReceiptSummaryModel(BaseModel):
    payment_type: str
    amount: float
    transaction_id: str
    payment_date: datetime
    receipt_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OldStudentBase(BaseModel):
    student_name: str
    admission_id: str | None = None
    roll_number: str | None = None
    course_name: str
    session: str
    mobile_number: str
    email: str | None = None
    category: str | None = None
    hostel_name: str | None = None
    block_name: str | None = None
    room_number: str | None = None
    bed_number: str | None = None
    old_student_status: str = "ACTIVE"


class OldStudentCreate(OldStudentBase):
    hostel_id: str


class OldStudentUpdate(OldStudentBase):
    pass


class OldStudentResponse(OldStudentBase):
    id: int
    hostel_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OldStudentListResponse(BaseModel):
    total: int
    items: list[OldStudentResponse]


class HostelIdGenerateRequest(BaseModel):
    count: int = 1


class HostelIdGenerateResponse(BaseModel):
    hostel_ids: list[str]
    prefix: str
    next_sequence: int


class ActivityLogBase(BaseModel):
    entity_type: str
    entity_id: str
    action: str
    old_values: str | None = None
    new_values: str | None = None


class ActivityLogResponse(ActivityLogBase):
    id: int
    admin_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityLogListResponse(BaseModel):
    total: int
    items: list[ActivityLogResponse]
