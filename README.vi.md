<div align="center">

# ⚖️ LabJury

**Framework ra quyết định đa phương thức, bất đồng bộ — để gán nhãn và kiểm duyệt ở quy mô lớn.**

*Bên đề xuất trình bày · trọng tài chấm điểm · phán quyết được tuyên.*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE)
[![Status](https://img.shields.io/badge/status-core-orange)]()

[English](./README.md) · Tiếng Việt

</div>

---

## LabJury là gì?

Phân loại nội dung ở quy mô lớn — gán nhãn video, kiểm duyệt quảng cáo, định
tuyến ticket — đang bóp nghẹt các đội ngũ theo hai cách cùng lúc: con người
không theo kịp khối lượng, còn AI hỗ trợ thì liên tục **bỏ sót vi phạm**,
**bỏ qua bất cứ thứ gì nó chưa có nhãn**, và **đọc sai sắc thái, tiếng lóng,
ẩn ý**.

LabJury là framework giúp làm việc phân loại đó một cách **chất lượng, rẻ, và
an toàn**. Ý tưởng cốt lõi là một cách chia việc:

> **Một model sinh ngôn ngữ *đề xuất* các nhãn ứng viên. Một model chỉ-ra-quyết-định
> *chấm điểm* chúng. Một policy *tuyên* phán quyết.**

Phần tốn kém (một LLM lớn *sinh* ra nhãn ứng viên) chỉ chạy một cách tiết kiệm.
Phần khối lượng lớn (*chấm điểm* các ứng viên đó) chạy trên một model nhanh,
rẻ, chỉ-ra-quyết-định — ví dụ [Jev](https://typesafe.ai) của TypeSafe AI, trả
về câu trả lời có kiểu (`Choice` / `Score` / `Noul`) kèm độ tin cậy thay vì
văn xuôi. Đó là thứ khiến **chất lượng, an toàn, và chi phí thấp** có thể dung
hòa ở mức hàng chục triệu item mỗi ngày.

### Về cái tên

**LabJury** = **LAB**(EL) + **JURY** (bồi thẩm đoàn). Kiến trúc *chính là* một
phiên tòa: nhiều tiếng nói trình bày bằng chứng — bản ghi lời thoại, chữ trong
ảnh, hashtag, các nhãn được đề xuất — một trọng tài cân nhắc chúng, và trả về
một phán quyết kèm độ tin cậy. Đọc như một backronym, nó nói ra đúng việc nó làm:

> **L**abeling **A**nd **B**atch **J**udgment **U**nder **R**anked
> **Y**ardsticks — *gán nhãn và phán quyết hàng loạt theo các thước đo đã xếp hạng.*

---

## Vì sao thiết kế như vậy

| Nguyên tắc | Ý nghĩa trong thực tế |
|---|---|
| **Không phụ thuộc cứng vào một model nào** | Jev chỉ là một `Scorer`. `LLMJudgeScorer` có sẵn cho phép cả pipeline chạy với bất kỳ chat LLM nào — nên bạn (và người đóng góp mã nguồn mở không có quyền truy cập Jev) không bao giờ bị kẹt. |
| **Taxonomy thế giới mở** | Nội dung không khớp nhãn nào sẽ được nêu lên như một *nhãn mới đề xuất* để người duyệt — **không bao giờ âm thầm bỏ qua**. Nhờ vậy kho nhãn lớn dần thay vì lỗi thời. |
| **An toàn thiên về bắt sót** | Một vi phạm khả nghi sẽ được **giữ lại chờ duyệt trừ khi trọng tài tự tin rằng nó sạch**. "Nghi ngờ thì giữ lại" — không bao giờ "không chắc thì thả qua". |
| **State đa phương thức, mở rộng được** | `text` · `json` · `image` · `audio` · `metadata` · `frame_sequence`, và bất kỳ kiểu nào bạn đăng ký. Lõi không bao giờ biết một tập modality *đóng*. |
| **Cơ chế xử lý nhanh, không phải bài toán scale** | Async toàn tuyến, gộp batch, giới hạn song song, backpressure tường minh, cache. Queue, lưu trữ, autoscale, và con đường tới 50M/ngày là hạ tầng của **bạn** — dựng *quanh* LabJury, không nằm trong nó. |
| **Plugin qua entry-points** | Ship một gói `pip` đăng ký dưới `labjury.<kind>`; lõi không cần đổi. |

---

## Luồng xử lý

```
          ┌──────────────┐   ┌───────────┐   ┌─────────┐   ┌───────────────┐   ┌──────┐
 item ──▶ │ ContextBuilder│──▶│ Proposer  │──▶│ Scorer  │──▶│ DecisionPolicy│──▶│ Sink │──▶ phán quyết
          └──────────────┘   └───────────┘   └─────────┘   └───────────────┘   └──────┘
            làm giàu state     đề xuất         chấm điểm       nhận / chặn /       định tuyến tới
           (ASR, OCR, …)       nhãn ứng viên   (Jev hoặc       giữ lại             DB / duyệt /
                                               LLM-judge)                          nhãn mới
                                   ▲
                                   └── bỏ qua ở "đường tắt thị giác"
```

**Định tuyến động, theo từng item.** Một item thuần hình ảnh (ví dụ ảnh chỉ cần
kiểm tra hở hang/logo cấm) bỏ qua bước Proposer đắt tiền và đi thẳng tới scorer
nhận ảnh. Chỉ những item khó về *ngữ nghĩa* (ẩn ý, lóng) mới đi đường dài.

---

## Bắt đầu nhanh (chạy không cần Jev)

```python
import asyncio
import labjury as lj

async def chat(prompt: str) -> str:
    # Cắm bất kỳ chat LLM bất đồng bộ nào vào đây; phải trả JSON {"value": ..., "confidence": ...}
    return '{"value": "food", "confidence": 0.95}'

class TextBuilder:
    accepts = frozenset({"*"}); produces = frozenset({"text"})
    async def build(self, item, state):
        state.add(lj.Content("text", item.raw["text"])); return state

class FoodProposer:
    accepts = frozenset({"*"})
    async def propose(self, state, context):   # context.known_labels = từ vựng chính thức
        return [lj.Candidate("food", "tag", lj.ChoiceQuestion("food_q", "food?", ["food"]))]

engine = lj.Engine(
    context_builders=[TextBuilder()],
    proposers=[FoodProposer()],
    scorers=[lj.LLMJudgeScorer(chat=chat)],   # thay bằng Jev scorer khi lên production
    policy=lj.RecallBiasedPolicy(),
    sink=lj.CollectingSink(),
    cache=lj.InMemoryCache(),
    taxonomy=lj.InMemoryTaxonomyStore(),
    observer=lj.InMemoryObserver(),
)

result = asyncio.run(engine.process(lj.Item("item-1", {"text": "món ăn ngon"})))
print(result.status, result.verdict)
```

---

## Hợp đồng `process_batch`

Một worker bên ngoài (đứng sau Kafka/queue của bạn) điều khiển engine. API
batch của nó là một **hợp đồng cố định** — người tích hợp dựa vào đó để scale:

- **Không theo thứ tự** — mỗi kết quả mang `correlation_id` của item, không phải vị trí trong danh sách.
- **Chịu lỗi từng phần** — một item hỏng trả về kết quả `FAILED`; các item còn lại vẫn được quyết định.
- **Backpressure tường minh** — item vượt quá `max_concurrency` trong một lần gọi sẽ trả `RETRY_LATER`, để caller đưa lại vào hàng đợi thay vì engine bị chặn.

---

## Mở rộng LabJury

Mỗi khâu là một plugin, được phát hiện qua entry-points. Trong `pyproject.toml`
của gói bạn:

```toml
[project.entry-points."labjury.scorers"]
my_jev = "my_package.scorers:JevScorer"
```

Rồi `labjury.load_entry_points()` sẽ nạp nó. Các loại plugin:
`context_builders`, `proposers`, `scorers`, `policies`, `sinks`,
`taxonomies`, `caches`.

### Taxonomy backend bền vững & tự xây

Từ vựng của taxonomy cần sống sót qua mỗi lần khởi động lại. Có sẵn backend
tham chiếu Redis:

```bash
pip install labjury[redis]
```

```python
from labjury.contrib.redis_taxonomy import RedisTaxonomyStore
engine = lj.Engine(..., taxonomy=RedisTaxonomyStore(async_redis_client))
```

Redis chỉ là một lựa chọn — bạn có thể dùng hệ store riêng (Postgres, DynamoDB,
store nội bộ) bằng cách hiện thực protocol `TaxonomyStore`, rồi kiểm chứng bằng
conformance suite có sẵn (`labjury.assert_taxonomy_store_contract`). Xem
[docs/taxonomy-backends.md](docs/taxonomy-backends.md).

### Audit trail (tùy chọn, độc lập storage)

Ghi một `AuditEvent` bất biến cho mỗi quyết định và replay lại sau:
`lj.Engine(..., audit=lj.InMemoryAuditLog())`. LabJury **không kèm database** —
dùng store riêng (Kafka/S3/SIEM/SQL) qua protocol `AuditLog` append-only và mối
nối `AuditEvent.to_dict`/`from_dict`, kiểm chứng bằng
`labjury.assert_audit_log_contract`. Có sẵn một backend SQLite bền vững
(`labjury.contrib.sqlite_audit.SqliteAuditLog`, không cần extra). Xem
[docs/audit-trail.md](docs/audit-trail.md).

### Metrics & telemetry (tùy chọn)

Mỗi kết cục terminal đi qua một `Observer`, và mỗi quyết định mang theo
`latency_ms` đầu-cuối. Có sẵn một exporter Prometheus tham chiếu
(`labjury.contrib.prometheus_observer.PrometheusObserver`, `pip install
labjury[prometheus]`) — counter theo kết cục cộng histogram độ trễ, còn endpoint
`/metrics` là của bạn. Cắm backend bất kỳ (OpenTelemetry, Datadog) qua cùng
protocol `Observer`. Xem [docs/observability.md](docs/observability.md).

### Plugin remote đáng tin cậy (tùy chọn)

Mọi plugin remote đều có thể được bọc để tăng độ tin cậy — `labjury.ReliableScorer`,
`ReliableProposer`, `ReliableContextBuilder` áp dụng timeout theo từng lần gọi,
retry kèm backoff, và circuit breaker (`breaker(retry(timeout(call)))`) lên bất kỳ
`Scorer`/`Proposer`/`ContextBuilder` nào — không phụ thuộc model, không thêm phụ
thuộc. Khi bỏ cuộc, lỗi nổi lên thành `ItemResult(FAILED)` để bên gọi đưa lại hàng
đợi. Xem [docs/reliability.md](docs/reliability.md).

---

## Lộ trình

- **Lõi (Core)** — chính là gói này. ✅
- **Plugin tham chiếu** — Jev scorer thật, proposer mạnh tiếng Việt, context builder ASR/OCR/trích frame, taxonomy & cache bền vững (Redis), và pipeline tham chiếu cho short-video + quảng cáo.
- **Service + client đa ngôn ngữ** — một service gRPC stateless (kèm REST/JSON tùy chọn) bọc engine, cùng các client mỏng sinh tự động cho **Java, Go, PHP, Python**, để đội ứng dụng dùng LabJury mà không phải đụng tới Python.

---

## Giấy phép

[Apache-2.0](./LICENSE)
