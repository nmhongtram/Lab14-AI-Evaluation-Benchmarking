# Reflection — Lab 14: AI Evaluation Factory
**Sinh viên:** Nguyen Mai Hong Tram  
**Ngày hoàn thành:** 2026-06-16  
**Email:** nguyenmaihongtram2004@gmail.com

---

## 1. Đóng góp cá nhân (Engineering Contribution)

Trong lab này tôi chịu trách nhiệm chính cho toàn bộ pipeline evaluation, bao gồm:

| Module | Công việc cụ thể |
|--------|-----------------|
| `data/synthetic_gen.py` | Thiết kế 50 static test cases bao gồm 4 nhóm độ khó: easy, medium, hard, adversarial. Tích hợp OpenAI GPT-4o-mini để sinh thêm cases tự động từ knowledge base 10 documents. |
| `engine/llm_judge.py` | Xây dựng Multi-Judge Consensus Engine với 2 model (GPT-4o-mini + GPT-4o). Implement logic phát hiện xung đột (diff > 1 điểm) và tự động tiebreak bằng model mạnh hơn. Tích hợp cost tracking chi tiết per-eval. |
| `engine/retrieval_eval.py` | Implement hàm `calculate_hit_rate()`, `calculate_mrr()` và method `score()` tích hợp vào pipeline chính. Xử lý riêng out-of-context cases (expected_ids rỗng). |
| `engine/runner.py` | Cập nhật async batch runner để truyền `expected_retrieval_ids` xuống agent, kết nối Retrieval Eval với Generation Eval. |
| `agent/main_agent.py` | Thiết kế V1 (hit_rate_target=72%) và V2 (88%) để tạo dữ liệu regression có ý nghĩa thống kê. |
| `main.py` | Xây dựng Release Gate tự động với 4 tiêu chí độc lập: avg_score, hit_rate, agreement_rate, no_regression. |

**Kết quả đạt được khi chạy thực tế:**
- Dataset: 61 test cases (7 adversarial, 26 easy, 8 hard, 20 medium)
- V2 Hit Rate: **98.2%** (tăng +14.3% so với V1)
- Thời gian benchmark: < 30 giây cho 61 cases (async)
- Chi phí per eval: $0.00074 USD

---

## 2. Hiểu biết kỹ thuật (Technical Depth)

### 2.1 Mean Reciprocal Rank (MRR) là gì và tại sao quan trọng?

Hit Rate chỉ cho biết "có tìm thấy document đúng không", nhưng không cho biết nó nằm ở **vị trí thứ mấy** trong danh sách kết quả. MRR giải quyết điều này:

```
MRR = (1/N) × Σ (1 / rank_i)
```

Ví dụ cụ thể từ lab này:
- Case A: document đúng ở vị trí 1 → MRR contribution = 1/1 = 1.0
- Case B: document đúng ở vị trí 3 → MRR contribution = 1/3 = 0.33
- Case C: không tìm thấy → contribution = 0

Trong kết quả thực tế, V2 đạt MRR = 0.756 so với V1 = 0.634. Điều này có nghĩa V2 không chỉ tìm thấy nhiều hơn mà còn **xếp hạng document đúng cao hơn trong top-3**. Điều này quan trọng trong RAG vì LLM thường ưu tiên context ở đầu danh sách (positional bias trong attention).

### 2.2 Agreement Rate và Cohen's Kappa — sự khác biệt

Trong lab này tôi dùng **Agreement Rate đơn giản** (tỉ lệ cases mà 2 judge lệch ≤ 1 điểm):

```
Agreement Rate = count(|score_A - score_B| ≤ 1) / total
```

**Cohen's Kappa** mạnh hơn vì loại bỏ phần đồng thuận ngẫu nhiên:

```
κ = (Po - Pe) / (1 - Pe)
```

Trong đó:
- `Po` = tỉ lệ đồng thuận quan sát thực tế
- `Pe` = tỉ lệ đồng thuận kỳ vọng nếu hai judge chấm ngẫu nhiên

**Tại sao lab này dùng Agreement Rate thay Kappa?** Vì với thang điểm liên tục 1–5 và số lượng cases nhỏ, Kappa có thể không ổn định. Agreement Rate (với threshold 1 điểm) đủ để phát hiện conflict thực sự. Nếu mở rộng lên 10.000+ cases, Cohen's Kappa sẽ là lựa chọn tốt hơn.

**Kết quả thực tế:** Agreement Rate chỉ đạt ~50%, cho thấy khoảng cách năng lực giữa GPT-4o-mini và GPT-4o khi đánh giá câu trả lời template là rõ rệt.

### 2.3 Position Bias trong LLM Judge

Position Bias xảy ra khi LLM judge đánh giá cao hơn response được đặt ở vị trí đầu tiên, bất kể nội dung thực tế. Đây là vấn đề đã được nghiên cứu kỹ trong các bài báo về LLM-as-a-Judge.

Trong `LLMJudge.check_position_bias()`, tôi implement phương pháp **swap test**:
1. Chấm điểm response_A ở position 1, response_B ở position 2
2. Đổi vị trí: response_B ở position 1, response_A ở position 2
3. Nếu điểm của cùng một response thay đổi > 0.5 khi đổi vị trí → có position bias

Hệ thống này chưa được gọi trong pipeline hiện tại (chỉ implement sẵn), nhưng cần được tích hợp khi so sánh 2 phiên bản agent trong A/B testing.

### 2.4 Trade-off Chất lượng vs Chi phí

Từ kết quả thực tế:

| Lựa chọn | Chi phí/eval | Agreement | Thời gian |
|----------|-------------|-----------|-----------|
| GPT-4o-mini only | ~$0.00003 | — | Nhanh nhất |
| GPT-4o only | ~$0.00070 | — | Chậm nhất |
| **Cả hai (hiện tại)** | **$0.00074** | **50%** | **Trung bình** |
| Smart escalation (đề xuất) | ~$0.00045 | ~65% | Nhanh |

**Đề xuất "Smart Escalation":** chạy GPT-4o-mini trước. Nếu score ≥ 4 hoặc case được tag là "easy", chấp nhận kết quả luôn. Chỉ escalate lên GPT-4o khi: score < 3, case là adversarial/hard, hoặc đây là case quan trọng (ví dụ: liên quan đến security policy). Ước tính tiết kiệm ~39% chi phí.

---

## 3. Thách thức và Cách giải quyết (Problem Solving)

### Thách thức 1: Windows console không hỗ trợ emoji trong Python 3.14

**Vấn đề:** `UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f527'` khi chạy trên terminal Windows (mặc định cp1252).

**Giải pháp:** Set biến môi trường `PYTHONUTF8=1` trước khi chạy:
```powershell
$env:PYTHONUTF8="1"; python data/synthetic_gen.py
```

**Bài học:** Khi viết code production, nên luôn dùng ASCII fallback cho logging hoặc set encoding tường minh bằng `sys.stdout.reconfigure(encoding='utf-8')` ở đầu file.

### Thách thức 2: OpenAI API trả về JSON object thay vì JSON array

**Vấn đề:** Khi dùng `response_format={"type": "json_object"}`, GPT-4o-mini đôi khi wrap kết quả trong một key như `{"cases": [...]}` thay vì trả về array trực tiếp.

**Giải pháp:** Parse linh hoạt:
```python
parsed = json.loads(raw)
cases = parsed if isinstance(parsed, list) else next(
    (v for v in parsed.values() if isinstance(v, list)), []
)
```

**Bài học:** LLM output luôn cần defensive parsing. Không nên assume format cứng, dù đã có system prompt rõ ràng.

### Thách thức 3: Agent mock trả lời template bị judge chấm điểm 1/5

**Vấn đề:** Ban đầu tôi tưởng đây là lỗi của judge, nhưng thực ra đây là **hành vi đúng** — judge đang phát hiện chính xác rằng agent không có Generation stage.

**Giải pháp:** Không sửa, mà dùng nó làm bằng chứng trong failure analysis. Đây là điểm then chốt của lab: evaluation framework phải phát hiện được lỗi của pipeline, không phải che giấu nó.

**Bài học:** Khi gặp kết quả "bất ngờ" trong evaluation, đừng vội sửa thresholds. Hãy hỏi: "Đây là lỗi của eval hay của system được eval?"

---

## 4. Insights về AI Evaluation

### Điều tôi hiểu sâu hơn sau lab này

**Retrieval ≠ Answer Quality:** V2 có Hit Rate 98.2% nhưng Answer Score chỉ 1.25/5. Điều này cho thấy Retrieval tốt là điều kiện cần nhưng không đủ. Một pipeline RAG hoàn chỉnh cần cả Retrieval + Generation đều tốt.

**"Garbage in, garbage out" áp dụng cho eval:** Nếu golden dataset có câu hỏi mơ hồ hoặc ground truth không chuẩn, judge sẽ đưa ra kết quả vô nghĩa. Đây là lý do tại sao giai đoạn SDG (Synthetic Data Generation) được dành 45 phút đầu tiên trong lab.

**Multi-Judge không phải là magic bullet:** Agreement Rate 50% của lab này cho thấy rằng hai model khác nhau vẫn có thể bất đồng đáng kể. Việc dùng 2 judge giúp phát hiện những case cần xem lại thủ công (conflict cases), không phải là đảm bảo độ chính xác tuyệt đối.

**Evaluation cũng có chi phí:** $0.090 USD cho 122 evaluations (V1 + V2) nghe có vẻ rẻ, nhưng khi scale lên 10.000 test cases và chạy mỗi ngày trong CI/CD, chi phí có thể lên $7.4/ngày hay $2.700/năm. Smart escalation và caching kết quả là cần thiết.

### Điều tôi muốn tìm hiểu thêm

- **RAGAS framework thực sự:** Lab này dùng RAGAS-proxy (heuristic), nhưng RAGAS thực sự dùng LLM để đánh giá Faithfulness và Answer Relevancy — muốn tìm hiểu kỹ hơn về implementation.
- **Cohen's Kappa trong practice:** Làm thế nào để set threshold κ phù hợp cho bài toán cụ thể.
- **Online evaluation:** Cách triển khai shadow mode để đánh giá agent trên production traffic mà không ảnh hưởng user.

---

## 5. Kết luận

Lab 14 đã giúp tôi hiểu rằng **"nếu không đo được thì không cải thiện được"** không chỉ là câu nói hay — nó là một engineering constraint thực sự. Xây dựng evaluation framework là công việc nghiêm túc, đòi hỏi kỹ năng thiết kế data, thống kê, và tối ưu chi phí, không khác gì xây dựng bản thân AI agent.

Thành quả lớn nhất của tôi trong lab này không phải là con số Hit Rate 98.2%, mà là nhận ra được rằng **framework eval đang hoạt động đúng khi nó báo cáo agent đang tệ** — đó chính xác là điều một evaluation factory tốt cần làm.
