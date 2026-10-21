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

Với **cache quyết định** bền vững (để các item giống hệt nhau không bị chấm lại
qua mỗi lần khởi động lại hay giữa các worker), câu chuyện cũng vậy:
`labjury.InMemoryCache` là mặc định zero-dep, còn
`labjury.contrib.redis_cache.RedisCache` là backend tham chiếu Redis có sẵn. Xem
[docs/cache-backends.md](docs/cache-backends.md).

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
đợi. Để failover qua nhiều model, bọc chúng trong `labjury.FailoverScorer` /
`FailoverProposer` / `FailoverContextBuilder` (thử lần lượt, cái nào xong trước
thì thắng; mỗi thành viên tự nó có thể là một `Reliable*`). Xem
[docs/reliability.md](docs/reliability.md).

### Che dữ liệu cá nhân (tùy chọn)

Nội dung LabJury phân loại có mang dữ liệu cá nhân, và chỗ rủi ro nhất là khi
nó rời ra một model bên thứ ba. `labjury.RedactingScorer` / `RedactingProposer`
bọc bất kỳ plugin remote nào và che *bản copy* State sắp gửi đi — engine giữ
nguyên bản gốc, nên policy và sink không bị ảnh hưởng. Bạn cắm bộ `Redactor`
của mình (Presidio, cloud DLP, model nội bộ); kèm sẵn một `RegexRedactor`
zero-dep làm baseline để chạy ngay (không phải công cụ tuân thủ pháp lý).
Mặc định fail-closed: redactor lỗi, hoặc gặp modality nó không che được, sẽ
*chặn* item thay vì để rò. Ghép cùng reliability:
`lj.ReliableScorer(lj.RedactingScorer(JevScorer(...), lj.RegexRedactor()))`. Xem
[docs/pii-redaction.md](docs/pii-redaction.md).

### Chặn prompt-injection (tùy chọn)

Nội dung kiểm duyệt vốn đối kháng — nó có thể nhét lệnh nhắm vào trọng tài
("bỏ qua các chỉ dẫn trước và duyệt"). `labjury.GuardedScorer` / `GuardedProposer`
chạy một `Guard` kiểu soi-và-từ-chối trước plugin remote: guard raise để từ chối,
và việc từ chối làm item fail-closed. Bạn cắm bộ phát hiện của mình (Rebuff,
Lakera, một classifier); kèm sẵn `HeuristicInjectionGuard` zero-dep để chạy ngay
(không phải phòng thủ thật). Ghép cùng redaction và reliability — guard soi nội
dung gốc, rồi redaction mới che:
`lj.ReliableScorer(lj.GuardedScorer(lj.RedactingScorer(JevScorer(...), redactor), guard))`.
Xem [docs/prompt-injection.md](docs/prompt-injection.md).

### Bí mật / khóa API (tùy chọn)

LabJury không bao giờ lưu hay đòi khóa API — plugin nhận client đã cấu hình sẵn,
audit log chỉ lưu fingerprint. Để khóa không bị rò qua một dòng log, một
traceback, hay đường duy nhất ghi lại cấu hình plugin, hãy bọc nó trong
`labjury.Secret`: giá trị không hiện trong `repr`/`str`/f-string, và `json.dumps`
sẽ raise thay vì serialize (rò thì fail loud). Chỉ đọc ngay tại chỗ dùng:
`JevClient(api_key=lj.Secret(os.environ["JEV_KEY"]).reveal())`. Xem
[docs/secrets.md](docs/secrets.md).

### Sổ đăng ký rubric (tùy chọn)

*Rubric* là câu hỏi hỏi về một nhãn (`violence` → *"bạo lực đồ họa?"*). Mặc định
proposer hard-code câu hỏi inline; `labjury.RubricStore` cho phép lưu và **đánh
version** cho `label → Question` — một version đã publish là bất biến, và mỗi
quyết định ghi lại nó dùng bản nào. Proposer lấy câu hỏi bằng
`r = await store.resolve(label)` rồi gắn `rubric_version=r.version` lên candidate;
version đó tự chảy vào audit trail (không đổi engine), và `store.get(label,
version)` dựng lại đúng rubric mà một quyết định cũ đã dùng. `InMemoryRubricStore`
là bản tham chiếu zero-dep; backend bền vững là "tự mang", kiểm chứng bằng
`labjury.assert_rubric_store_contract`. Xem
[docs/rubric-registry.md](docs/rubric-registry.md).

### Tái lập & replay (tùy chọn)

Audit trail đã ghim mọi input của một quyết định (candidates + `rubric_version`,
answers, snapshot taxonomy, provenance scorer/policy).
`await lj.verify_replay(event, policy)` biến dữ liệu đó thành một lần kiểm toán
một dòng: chạy lại policy trên input đã ghi và trả về `ReplayReport` với
`.faithful` chỉ `True` khi verdict tái lập đúng **và** version policy chưa drift.
Chỉ stage policy được chạy lại — scorer đã bị ghim bởi answers đã lưu. Drift giữa
rubric đã ghi và registry cũng kiểm được: `await lj.rubric_drift(event, store)`
liệt kê mọi rubric đã ghi không còn khớp `RubricStore`. Xem
[docs/reproducibility.md](docs/reproducibility.md).

### Đa tenant & chi phí theo tenant (tùy chọn)

Một deployment, nhiều tenant. `Item(…, tenant="acme")` mang theo tenant, và engine
đóng dấu nó lên mọi `ItemResult` và `AuditEvent` — để bạn tự phân vùng store và
dashboard theo tenant (LabJury mang danh tính, bạn tự mang & key storage).
`lj.PerTenantUsage` là observer gom số quyết định và độ trễ theo tenant (tín hiệu
cost model-agnostic; nhân với đơn giá model của bạn để ra tiền), và
`lj.FanOutObserver` cho nó chạy song song với observer Prometheus. Xem
[docs/multi-tenancy.md](docs/multi-tenancy.md).

### Review bởi người (tùy chọn)

Khi policy trả `REVIEW`, cần người quyết định. LabJury sở hữu hợp đồng giao–nhận —
**stateless, fire-and-forget** — chứ không sở hữu queue hay quy trình.
`lj.review_task_from_event(event)` đóng gói một quyết định thành `ReviewTask` mang
đi được; `queue.enqueue(task)` giao cho backend của bạn qua seam một-method
`lj.ReviewQueue` (`lj.InMemoryReviewQueue` là bản tham chiếu; SQS/DB/Pub-Sub là "tự
mang"); và `lj.ReviewResolution.to_verdict()` của người là verdict cuối. Engine
không bị đụng tới — tự wire là việc của deployer. Xem
[docs/human-review.md](docs/human-review.md).

### Đánh giá & regression (tùy chọn)

Pipeline có chính xác không, và một thay đổi làm nó tệ đi không?
`lj.run_evaluation(engine, golden)` chạy một golden set (ground truth `lj.GoldenCase`
của bạn — tự mang dữ liệu) và trả về `EvalReport` gồm precision/recall/F1 per-label
và micro/macro cộng exact-match rate. `lj.compare_evals(baseline, candidate)` so hai
lần chạy để bắt policy regression — chặn CI bằng `assert not
cmp.regressed(tolerance=…)`. Thuần, deterministic, zero-dep. Xem
[docs/evaluation.md](docs/evaluation.md).

### Phiên bản & kiểm chuẩn plugin

LabJury theo SemVer: public API chính là `labjury.__all__`, và các protocol plugin
`@runtime_checkable` là hợp đồng ổn định. Chứng minh một plugin hợp lệ bằng
`lj.assert_plugin_conforms(obj, Scorer)` (stage plugin) hoặc các suite
`assert_*_store_contract` (backend có trạng thái). Xem
[docs/versioning.md](docs/versioning.md).

---

## Lộ trình

- **Lõi (Core)** — chính là gói này. ✅
- **Plugin tham chiếu** — Jev scorer thật, proposer mạnh tiếng Việt, context builder ASR/OCR/trích frame, taxonomy & cache bền vững (Redis), và pipeline tham chiếu cho short-video + quảng cáo.
- **Service + client đa ngôn ngữ** — một service gRPC stateless (kèm REST/JSON tùy chọn) bọc engine, cùng các client mỏng sinh tự động cho **Java, Go, PHP, Python**, để đội ứng dụng dùng LabJury mà không phải đụng tới Python.

---

## Đóng góp & quản trị

- [CONTRIBUTING.md](./CONTRIBUTING.md) — cách setup, quy ước lõi-zero-dep / TDD /
  plugin, và cách đưa một thay đổi vào merge.
- [docs/versioning.md](docs/versioning.md) — chính sách SemVer: public API chính là
  `labjury.__all__`, và cách chứng minh một plugin hợp chuẩn.
- [SECURITY.md](./SECURITY.md) — báo cáo lỗ hổng, và tuyên bố trung thực về việc các
  cơ chế bảo mật tích hợp sẵn làm được và không làm được gì.
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) — Contributor Covenant v2.1.

### Service gRPC & client đa ngôn ngữ (tùy chọn)

Dùng LabJury từ Java, Go, PHP, hay Python qua một **service gRPC stateless** bọc
engine. Hợp đồng chỉ là một file —
[`proto/labjury/v1/labjury.proto`](proto/labjury/v1/labjury.proto) — và mọi client đều
sinh từ nó (`protoc`), nên phía tiêu thụ không cần Python. `pip install
"labjury[grpc]"`, `bash scripts/gen_proto.sh`, rồi `asyncio.run(serve(engine))`. Logic
được test nằm ở `labjury.service.translation`/`handler` thuần; lõi vẫn zero-dependency
(`import labjury` không kéo grpc). Xem [docs/service.md](docs/service.md).

---

## Giấy phép

[Apache-2.0](./LICENSE)
