# L3A Architecture Record

Hệ thống điều tra khiếu nại thương mại điện tử Multi-Agent L3A phối hợp giữa Coordinator, các Specialist chuyên trách, MCP Evidence Gateway và Verifier để đưa ra quyết định giải quyết khiếu nại khách hàng dựa trên bằng chứng có thẩm quyền và hợp đồng công khai.

## 1. System overview

Luồng xử lý từ input case đến output và trace audit:

```text
                  inputs/<case_id>.json
                            │
                            ▼
                    ┌──────────────┐
                    │ Coordinator  │◄───────────────────────────┐
                    └──────┬───────┘                            │
             task_assigned │ ▲ handoff (EVIDENCE_READY)         │
                           ▼ │                                  │
                  ┌──────────────────┐                          │
                  │   Specialists    │                          │
                  │ (Order, Payment, │                          │
                  │ Shipment, Policy)│                          │
                  └────────┬─────────┘                          │
                           │ call_tool (scoped case_id)         │
                           ▼                                    │
               ┌───────────────────────┐                        │
               │  MCP Evidence Gateway │                        │
               └───────────┬───────────┘                        │
                           │ structured evidence envelope       │
                           ▼                                    │
                  ┌──────────────────┐                          │
                  │   Case Context   │─── emit ─────────────┐   │
                  │(Evidence & Cache)│                      │   │
                  └────────┬─────────┘                      │   │
                           │ reconciled findings            │   │
                           ▼                                │   │
                    ┌──────────────┐ policy_decided         │   │
                    │ Policy Agent │─────────────────┐      │   │
                    └──────────────┘                 │      │   │
                                                     ▼      ▼   │
                                              ┌───────────────┐ │
                                              │   Verifier    │─┘
                                              └──────┬────────┘
                                                     │ verify_output
                                                     ▼
                                            outputs/<case_id>.json
                                            traces/trace.jsonl
```

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Output/handoff | Allowed MCP Tools |
| --- | --- | --- | --- | --- |
| **coordinator** | `case` object từ `inputs/<case_id>.json` | Điều phối toàn bộ vòng đời case, phân rã nhiệm vụ cho specialist, nhận handoff, kích hoạt verifier và finalize case. | `task_assigned` tới các specialist, `case_received`, `case_finalized` | Không gọi tool trực tiếp |
| **order-agent** | `claimed_order_id`, `case_id` | Thu thập thông tin đơn hàng, danh sách item, hạn giao hàng (shipping limit date) và seller liên quan. | Handoff `EVIDENCE_READY` kèm `evidence_ref` | `get_order`, `get_order_items`, `get_sellers` |
| **payment-agent** | `claimed_order_id`, `case_id`, claim topics | Thu thập lịch sử payment captures, đối soát số tiền đã thanh toán và lịch sử refund (nếu có claim refund). | Handoff `EVIDENCE_READY` hoặc `REFUND_EVIDENCE_UNAVAILABLE` | `get_payment_timeline`, `get_refund_timeline` |
| **shipment-agent** | `claimed_order_id`, `case_id` | Thu thập tóm tắt vận chuyển: thời điểm bàn giao carrier, thời điểm giao khách, ước tính giao hàng và sự kiện trễ. | Handoff `EVIDENCE_READY` kèm `evidence_ref` | `get_shipment_summary` |
| **policy-agent** | `policy_version`, reconciled findings | Truy vấn policy có thẩm quyền từ MCP, đối chiếu quy tắc theo nguyên nhân chính để xác định status, action, refund và bên chịu trách nhiệm. | Handoff `POLICY_DECIDED` chuyển cho Verifier | `get_policy` |
| **verifier** | Candidate output, accumulated evidence, contracts | Kiểm tra tính bất biến độc lập (schema, case scope, evidence citation, Decimal money sum, consistency, cause rank). | Handoff `VERIFIED` về coordinator | Không gọi tool trực tiếp |

Mọi agent chỉ được phép truy vấn các tool trong allowlist được khai báo bất biến (`frozenset`). Mọi hành vi gọi ngoài danh sách sẽ bị từ chối ngay lập tức.

## 3. A2A protocol

- **Message Envelope**: Tuân thủ nghiêm ngặt schema `day09-trace-event-v1`, bao gồm: `schema_version`, `event_id`, `case_id`, `event_type`, `occurred_at`, `actor`, `target`, `decision_code`, `evidence_refs`, `attributes`.
- **Correlation**: Mọi event đều gắn chặt với `case_id`. Không có sự kiện nào mang case_id rỗng hoặc lệch với case đang xử lý.
- **Vòng đời & Handoff**:
  1. `coordinator` phát `case_received`.
  2. `coordinator` phát `task_assigned` tới từng specialist với `tool` cụ thể.
  3. `specialist` tiêu thụ evidence và phát `tool_result_consumed`.
  4. `specialist` phát `handoff` về `coordinator` với `decision_code="EVIDENCE_READY"`.
  5. `policy-agent` xác lập quyết định và phát `policy_decided` tới `verifier`.
  6. `coordinator` giao nhiệm vụ `task_assigned` (`VERIFY_OUTPUT`) cho `verifier`.
  7. `verifier` kiểm tra và phát `verification_completed` (`decision_code="VERIFIED"`).
  8. `coordinator` hoàn tất với `case_finalized`.
- **Tránh vòng lặp**: Pipeline luồng dữ liệu định hướng một chiều (DAG), không có đệ quy (no recursive delegation), không cho phép giao tiếp vòng lặp giữa các specialist.

## 4. Evidence lifecycle

- **Thu thập & Validate**: Mỗi kết quả trả về qua `EvidenceGateway.call` được validate với `mcp-evidence-response-v1.schema.json`. `evidence_ref` và `result_hash` do MCP cấp được giữ nguyên vẹn.
- **Tiêu thụ (Consumption)**: Mỗi khi bằng chứng được nạp vào context của agent, một event `tool_result_consumed` được ghi lại ngay trong trace với đúng `evidence_ref`.
- **Mapping & Citation**:
  - `output.evidence_refs` chỉ chứa các `evidence_ref` thật từ các domain liên quan trực tiếp đến kết luận.
  - Mọi `evidence_ref` trong `claim_assessments` bắt buộc phải là tập con của `output.evidence_refs`.
  - Mọi `evidence_ref` trong output bắt buộc phải nằm trong các `tool_result_consumed` đã ghi trong trace của case đó.
- **Phạm vi cô lập (Case Scope)**: `CaseContext` được khởi tạo mới hoàn toàn cho mỗi case. Cache bằng chứng bị hủy khi chuyển case. Nghiêm cấm trích dẫn chéo bằng chứng giữa các case khác nhau.

## 5. Failure policy

| Failure | Retry? | Fallback | Trace event/code |
| --- | --- | --- | --- |
| MCP timeout / Connection error | Tối đa 3 lần với exponential backoff (1s, 2s), timeout 90s/lần | Fails closed nếu sau 3 lần vẫn lỗi (bảo vệ tính toàn vẹn audit) | `handoff` với `decision_code="MCP_TIMEOUT"`, attribute `attempt` |
| Not found / Tool error (ví dụ: thiếu refund history) | Không retry nếu là tool error nghiệp vụ | Không đoán dữ liệu; fallback sang `insufficient_evidence` với confidence 0.3 | `handoff` với `decision_code="REFUND_EVIDENCE_UNAVAILABLE"` |
| Source conflict (lệch purchase date hoặc seller ID) | Không retry | Phân giải có nguyên tắc: ưu tiên payment episode cho purchase time; ưu tiên item seller cho seller responsibility; ghi nhận vào `data_conflicts` | Ghi nhận trong output `data_conflicts` với `resolution_code` rõ ràng |
| Invalid specialist result / Schema fail | Không retry | Verifier từ chối phê duyệt, quăng ngoại lệ ngăn chặn ghi đè output sai | Fails trước khi phát `verification_completed` |

## 6. Verification invariants

Trước khi chấp thuận và phát `verification_completed`, hàm `verify_output` kiểm tra:
1. **Schema compliance**: Tuân thủ JSON Schema `l3a-output-v2.schema.json`.
2. **Case ID consistency**: `output.case_id == active_case_id`.
3. **Evidence validity**: `evidence_refs` không rỗng và phải là tập con của các bằng chứng đã thu thập trong phiên xử lý case hiện tại.
4. **Claim evidence linkage**: Mọi `evidence_refs` trong từng `claim_assessments` phải thuộc `output.evidence_refs`.
5. **Decimal monetary precision**: `sum(line.amount_brl for line in refund_lines) == recommended_refund_brl` với độ chính xác số học Decimal (tránh lỗi làm tròn float).
6. **Status / Refund consistency**: Nếu `recommended_refund_brl > 0`, `case_status` không được là `no_action`.
7. **Root cause ranking**: Các giá trị `rank` trong `ranked_causes` phải là dãy số nguyên liên tục bắt đầu từ 1 đến N (`1, 2, ..., N`).

## 7. Reproducibility

- **Môi trường**: Python 3.11+ (kiểm thử trên Python 3.12 Windows).
- **Dependencies**: Được ghim cụ thể trong `pyproject.toml` và `requirements-lock.txt` (`httpx2>=2,<3`, `mcp>=2,<3`, `jsonschema>=4.25,<5`, `python-dotenv>=1.1,<2`).
- **Deterministic logic**: Không phụ thuộc vào LLM model call tại runtime giải case; thuật toán multi-agent specialist phân tích có tính xác định cao (deterministic), loại bỏ biến thiên ngẫu nhiên (temperature / seed không làm ảnh hưởng kết quả).
- **Giới hạn tài nguyên & Concurrency**: Xử lý tuần tự 100 cases trong 1 session MCP có kiểm soát kết nối và timeout 90s, đảm bảo thứ tự audit log trên server.
- **Quy trình chạy chuẩn**:
  ```powershell
  # 1. Kiểm tra input
  day09 validate-inputs
  # 2. Khởi tạo session run và chạy toàn bộ workflow
  day09 run
  # 3. Kiểm định output và trace theo hợp đồng
  day09 validate
  # 4. Đóng gói file nộp bài
  day09 package --output dist/submission.zip
  ```
