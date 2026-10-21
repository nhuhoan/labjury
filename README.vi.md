<div align="center">

# ⚖️ LabJury

**Framework Python mã nguồn mở để gán nhãn và kiểm duyệt nội dung ở quy mô lớn.**

*Bên đề xuất trình bày, giám khảo chấm điểm, phán quyết được tuyên.*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE)
[![Status](https://img.shields.io/badge/status-core-orange)]()

[English](./README.md) · Tiếng Việt

</div>

---

## LabJury là gì?

LabJury là framework bất đồng bộ, hướng plugin để phân loại và kiểm duyệt nội
dung khi khối lượng lớn tới mức gọi một LLM cho từng mục trở nên quá tốn kém.

Ở quy mô lớn, như gán nhãn video, kiểm duyệt quảng cáo hay định tuyến ticket, mọi
thứ gãy ở hai đầu cùng lúc: con người duyệt không xuể, còn AI hỗ trợ thì bỏ sót vi
phạm, lúng túng trước nội dung chưa từng gặp, và hiểu sai tiếng lóng hay ẩn ý.
LabJury giải quyết bằng cách tách một việc khó thành hai việc dễ hơn:

> `Proposer` cung cấp các nhãn ứng viên. `Scorer` đánh giá chúng. Policy *tuyên*
> phán quyết cuối. Bạn chọn mô hình đứng sau các plugin đó.

Chi phí phụ thuộc proposer, scorer, tuyến xử lý và tỷ lệ cache hit được cấu hình.
Trên đường văn bản mặc định, proposer chạy cho từng mục. Cần đo cả hai bước so với
cách gọi LLM trực tiếp trước khi khẳng định tiết kiệm chi phí.

Tên gọi ghép từ **LAB**EL và **JURY** (bồi thẩm đoàn). Một mô hình đoán nhãn chỉ là
một ý kiến đơn lẻ. LabJury xử lý như một phiên tòa: trình bày bằng chứng gồm lời
thoại, chữ trong ảnh, hashtag và các nhãn ứng viên, cân nhắc, rồi đưa ra phán quyết
kèm độ tin cậy.

### Jev và LLMJudgeScorer

Jev là model chuyên ra quyết định của TypeSafe AI. Thay vì tạo văn bản dài dòng, Jev
đưa ra kết quả trực tiếp: chọn phương án, chấm điểm hoặc gán nhãn, kèm độ tin cậy.

Trong LabJury, Jev có thể đóng vai trò giám khảo, đánh giá từng nhãn ứng viên. Tốc
độ và chi phí phụ thuộc cách triển khai model và toàn bộ pipeline.

Chưa có Jev? `LLMJudgeScorer` tích hợp sẵn chấm nội dung text, JSON và metadata qua
hàm async `chat(prompt)` do bạn truyền vào. Bạn tự cấu hình client, model, API key
và `base_url` tùy chỉnh, rồi chuyển response thành chuỗi JSON có `value` và
`confidence`. Bản lõi không kèm client cho OpenAI, Claude, model local hay Jev.

---

## Dùng khi nào, chưa cần khi nào

Dùng LabJury khi:

- Bạn kiểm duyệt hoặc phân loại nội dung ở khối lượng lớn, và chi phí gọi LLM cho
  từng mục trở nên quá cao.
- Bạn cần quyết định an toàn, giải thích được và kiểm toán lại được, thay vì một con
  số từ hộp đen.
- Bộ nhãn của bạn còn thay đổi, và bạn muốn proposer nêu ứng viên mới cho policy
  cùng người duyệt xem xét.
- Bạn muốn tự chọn mô hình, nơi lưu trữ và hạ tầng, không bị khóa vào một nhà cung cấp.

Chưa cần LabJury khi:

- Bạn chỉ phân loại vài trăm mục. Gọi thẳng một LLM đơn giản hơn và đủ dùng.
- Bạn muốn một sản phẩm cắm là chạy, kèm sẵn queue, database và dashboard. LabJury là
  framework, bạn dựng hạ tầng quanh nó.
- Bạn cần một mô hình dựng sẵn cho tiếng Việt hay cho ảnh ngay hôm nay. Lõi không kèm
  mô hình nào sẵn, bạn tự gắn mô hình của mình vào. `LLMJudgeScorer` là điểm tích hợp
  cho chat LLM xử lý văn bản mà bạn tự kết nối.

---

## Bắt đầu nhanh (chạy không cần Jev)

```python
import asyncio
import labjury as lj

async def chat(prompt: str) -> str:
    # Hàm giả: luôn trả "food", bất kể prompt.
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
    scorers=[lj.LLMJudgeScorer(chat=chat)],
    policy=lj.RecallBiasedPolicy(),
    sink=lj.CollectingSink(),
    cache=lj.InMemoryCache(),
    taxonomy=lj.InMemoryTaxonomyStore(),
    observer=lj.InMemoryObserver(),
)

result = asyncio.run(engine.process(lj.Item("item-1", {"text": "món ăn ngon"})))
print(result.status, result.verdict)
```

Ví dụ này minh họa pipeline, không kiểm chứng độ chính xác của model. Khi dùng LLM
thật, thay `chat` bằng hàm async gọi client đã cấu hình. Hàm nhận nội dung mục và
câu hỏi trong prompt, rồi trả chuỗi JSON có `value` và `confidence` (`0..1`). Bước
đề xuất nhãn bằng LLM cần một plugin `Proposer` riêng; judge tích hợp chỉ chấm câu
hỏi đã được cung cấp.

Khi dùng cache chia sẻ như Redis, đặt `cache_namespace` trên `Engine` thành phiên bản
deployment ổn định và đổi nó mỗi khi model hoặc logic quyết định bên ngoài thay đổi.
Nếu không đặt, mỗi instance có namespace riêng. Cache hit vẫn chạy context builder
và proposer; nó bỏ qua scorer và policy khi ngữ cảnh quyết định hiện tại khớp.
Verdict `REVIEW` được chấm lại cho từng mục để audit giữ đủ bằng chứng cho người duyệt.

---

## Cách hoạt động

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

Định tuyến chạy động theo từng mục. Mục thuần hình ảnh có thể bỏ qua Proposer và đi
thẳng tới scorer xử lý ảnh khi bạn cung cấp scorer đó cùng các câu hỏi cố định.
Lõi chỉ cung cấp kiểu nội dung và routing; không kèm model ảnh/video, OCR, ASR hay
trích frame. Văn bản và nội dung cần xử lý ngữ nghĩa đi qua proposer.

Một worker bên ngoài, đứng sau Kafka hay queue của bạn, điều khiển engine qua
`process_batch`. API này là một hợp đồng cố định để bạn dựa vào mà mở rộng. Kết quả
trả về không theo thứ tự, mỗi kết quả mang `correlation_id` của chính nó. Một mục
hỏng trả về `FAILED` mà không kéo các mục khác theo. Mục vượt `max_concurrency` trả
về `RETRY_LATER`, để bạn đưa lại vào hàng đợi thay vì để engine bị chặn.

---

## Vì sao thiết kế như vậy

| Nguyên tắc | Ý nghĩa trong thực tế |
|---|---|
| Không khóa vào một mô hình | Jev là một lựa chọn `Scorer`; `LLMJudgeScorer` nhận adapter async cho chat LLM. Bạn tự cấp client và chuẩn hóa response JSON. |
| Taxonomy thế giới mở | Proposer có thể đưa ra nhãn mới; policy đề xuất nó vào taxonomy khi đáp án đạt điều kiện, còn ứng viên thiếu hoặc chưa chắc chắn được đưa review. |
| An toàn thiên về bắt sót | Nếu giám khảo không đủ tự tin rằng nội dung sạch, mục bị giữ lại chờ duyệt. Thà chặn nhầm một quảng cáo sạch còn hơn để lọt một vi phạm. |
| State đa phương thức | `text`, `json`, `image`, `audio`, `metadata`, `frame_sequence` và kiểu tùy chỉnh là vùng chứa và tín hiệu routing. Xử lý media cần plugin của bạn. |
| Cơ chế xử lý nhanh | Async toàn tuyến, gộp batch, giới hạn song song, backpressure, cache. Queue, lưu trữ và autoscale là hạ tầng của bạn, dựng quanh LabJury. |
| Plugin qua entry-points | Ship một gói `pip` đăng ký dưới `labjury.<kind>`; lõi không cần đổi. |

---

## Tính năng

Khi cài, bản lõi của LabJury không kéo theo thư viện ngoài nào. Mọi tính năng dưới
đây đều không bắt buộc: bạn chỉ bật thứ mình cần. Bấm vào link để xem chi tiết.

**Độ tin cậy và vận hành**

- **Audit trail và replay** — ghi lại một `AuditEvent` bất biến cho mỗi quyết định,
  rồi chạy lại để kiểm toán về sau. Storage là của bạn (Kafka, S3, SQL), kèm một
  backend SQLite tham chiếu. [docs](docs/audit-trail.md) ·
  [tái lập](docs/reproducibility.md)
- **Chống lỗi khi gọi qua mạng** — mô hình của bạn gọi qua mạng, mà mạng thì lúc
  chậm lúc sập. Bọc scorer lại để nó tự đặt giới hạn thời gian chờ, thử lại khi lỗi
  tạm thời, ngắt mạch khi service chết, và nhảy sang mô hình dự phòng.
  [docs](docs/reliability.md)
- **Metrics và telemetry** — mọi kết cục đi qua một `Observer`, kèm `latency_ms`. Có
  sẵn exporter Prometheus tham chiếu, và bạn nối OpenTelemetry hay Datadog qua cùng protocol.
  [docs](docs/observability.md)
- **Đa tenant và chi phí** — một deployment phục vụ nhiều tenant; đếm số quyết định,
  độ trễ và token theo từng tenant. [docs](docs/multi-tenancy.md) ·
  [cost](docs/cost-metering.md)

**An toàn**

- **Che dữ liệu cá nhân (PII)** — che bản copy của `State` trước khi nó rời ra một
  mô hình bên thứ ba. Lỗi che dữ liệu trả `FAILED` trước khi gọi model được bọc.
  [docs](docs/pii-redaction.md)
- **Chặn prompt-injection** — nội dung kiểm duyệt có thể nhét lệnh nhắm vào giám khảo
  ("bỏ qua chỉ dẫn trước và duyệt"). Soi và từ chối trước khi gửi đi.
  [docs](docs/prompt-injection.md)
- **Bảo vệ khóa API** — `lj.Secret` che `str`/`repr` của chính nó và từ chối ghi ra
  JSON. Bạn vẫn phải cấu hình client và kiểm soát log, lỗi của provider sau khi mở
  khóa. [docs](docs/secrets.md)

**Chất lượng và quản trị**

- **Sổ đăng ký rubric** — lưu và đánh version cho `nhãn → câu hỏi`. Mỗi quyết định
  ghi lại nó dùng bản nào, nên bạn dựng lại được đúng câu hỏi của một quyết định cũ.
  [docs](docs/rubric-registry.md)
- **Đánh giá và regression** — chấm pipeline trên golden set của bạn (precision,
  recall, F1), so hai lần chạy để chặn regression ngay trong CI. [docs](docs/evaluation.md)
- **Review bởi người** — khi policy trả `REVIEW`, một người quyết định. LabJury giữ
  hợp đồng giao nhận stateless, còn queue là của bạn. Quyết định ghi đè của người cũng
  được audit. [docs](docs/human-review.md)
- **SemVer và kiểm chuẩn plugin** — public API chính là `labjury.__all__`. Chứng minh
  một plugin hợp lệ bằng `assert_plugin_conforms`. [docs](docs/versioning.md)

**Tích hợp và lưu trữ**

- **Storage tự mang** — taxonomy, cache và audit đều là protocol bạn tự hiện thực
  (Postgres, DynamoDB, store nội bộ), kiểm chứng bằng conformance suite có sẵn. Kèm
  backend Redis và SQLite tham chiếu. [taxonomy](docs/taxonomy-backends.md) ·
  [cache](docs/cache-backends.md)
- **Service gRPC tham chiếu** — có sẵn server binding Python và hợp đồng `.proto`.
  Bạn tự sinh stub cho server và client Java, Go, PHP hoặc Python; phần triển khai
  và bảo mật transport do bạn phụ trách. [docs](docs/service.md)

---

## Mở rộng

Mỗi khâu là một plugin, phát hiện qua entry-points. Trong `pyproject.toml` của gói bạn:

```toml
[project.entry-points."labjury.scorers"]
my_jev = "my_package.scorers:JevScorer"
```

Rồi `labjury.load_entry_points()` sẽ nạp nó. Các loại plugin: `context_builders`,
`proposers`, `scorers`, `policies`, `sinks`, `taxonomies`, `caches`. Xem
[CONTRIBUTING.md](./CONTRIBUTING.md) cho quy ước lõi-zero-dep, TDD và cách merge.

---

## Câu hỏi thường gặp

**LabJury có bắt buộc dùng Jev không?**
Không. Jev là một lựa chọn `Scorer`. Pipeline văn bản dùng được `LLMJudgeScorer`
khi bạn cung cấp adapter async trả JSON đúng định dạng. Bắt đầu nhanh với văn bản
không cần Jev.

**Có bị khóa vào một nhà cung cấp không?**
Không. Mô hình, taxonomy, cache, audit, metrics và queue review đều là protocol bạn
tự hiện thực rồi nối vào. LabJury mang cơ chế, bạn mang mô hình và storage.

**LabJury có kèm database hay message queue không?**
Không. Bản lõi không phụ thuộc thư viện ngoài nào. Có sẵn backend tham chiếu (Redis,
SQLite, Prometheus) sau các gói cài thêm tùy chọn, còn `import labjury` không kéo theo
thứ gì.

**Khác gì so với gọi thẳng một LLM để gán nhãn?**
Gọi thẳng LLM hỏi "nhãn là gì?" cho từng mục. LabJury tách bước đề xuất nhãn khỏi
bước chấm điểm, giữ lại audit trail và cho phép chặn regression. Chi phí phụ thuộc
model và tuyến xử lý bạn cấu hình; đường văn bản mặc định vẫn chạy proposer cho mỗi
mục, nên cần benchmark so với cách gọi LLM trực tiếp.

**Chạy được tới quy mô nào?**
LabJury lo phần cơ chế xử lý nhanh: async, batch, giới hạn song song, backpressure,
cache. Con đường tới hàng chục triệu mục mỗi ngày là hạ tầng của bạn, gồm queue, lưu
trữ và autoscale, dựng quanh nó.

**Dùng được từ Java, Go hay PHP không?**
Được, sau khi bạn sinh client stub từ file `.proto` kèm sẵn và chạy service Python
tham chiếu với server stub đã sinh. Xem [docs/service.md](docs/service.md).

**Đã dùng được cho production chưa?**
Đây là bản lõi giai đoạn đầu, có test và chính sách SemVer cho public API
(`labjury.__all__`). Triển khai production vẫn cần plugin gọi model thật, backend
bền vững, bảo mật và vận hành riêng.

---

## Lộ trình

- **Lõi (Core)** — chính là gói này. ✅
- **Plugin tham chiếu** — Jev scorer thật, proposer mạnh tiếng Việt, context builder
  ASR/OCR/trích frame, và pipeline tham chiếu cho short-video và quảng cáo.
- **Triển khai service và gói client** — hoàn thiện service gRPC tham chiếu, tùy chọn
  REST/JSON và phát hành client sinh sẵn cho các ngôn ngữ khác.

---

## Đóng góp và quản trị

- [CONTRIBUTING.md](./CONTRIBUTING.md) — cách setup, quy ước lõi-zero-dep / TDD /
  plugin, và cách đưa một thay đổi vào merge.
- [docs/versioning.md](docs/versioning.md) — chính sách SemVer và cách chứng minh một
  plugin hợp chuẩn.
- [SECURITY.md](./SECURITY.md) — báo cáo lỗ hổng, và tuyên bố trung thực các cơ chế
  bảo mật tích hợp làm được và không làm được gì.
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) — Contributor Covenant v2.1.

---

## Giấy phép

[Apache-2.0](./LICENSE)
