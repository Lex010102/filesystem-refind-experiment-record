# Figure 4.1 Generation Specification

- **Tool mode:** Built-in image generation
- **Use case:** `infographic-diagram`
- **Style references:** Figure 3.1 and Figure 1.5

## Final Prompt

Create a polished, wide 16:9 academic infographic titled **“Experimental Design and Evaluation Workflow”**, with the subtitle **“Frozen inputs produce 900 candidate answers for blind offline evaluation and paired analysis”**. Match the report's existing white-background visual language: dark navy headings, teal and indigo accents, restrained orange for Full Context, rounded cards, subtle shadows, consistent line icons, straight connectors, medium triangular arrowheads, generous spacing, and no crossing arrows.

Build one coherent top-to-bottom workflow with five aligned levels:

1. **Frozen experimental inputs** containing **Main-60 questions**, **Canonical conversation**, and **S1–S3 frozen stores**.
2. Three equal branches: **Qwen · E1–E7 / 420 answers**, **DeepSeek · E1–E7 / 420 answers**, and **DeepSeek Full Context / 60 answers**.
3. One converged card: **900 candidate answers**.
4. **Blind offline evaluation**, containing four equal cards: **Token quality / Precision · Recall · F1**; **Semantic quality / Strict · Partial · Soft**; **Evidence access / Recall · Any-hit · All-hit / N/A for Full Context**; and **Process and cost / Calls · Tokens · Latency**. Add a separate dashed card **Gold answers + gold evidence**, connected only to offline evaluation by a dashed arrow labelled **offline only**.
5. **Paired analysis and error review**, containing **Same-question contrasts**, **Category · DID · CoC**, **Selected paired bootstrap**, and **Stage-based error review**.

Finish with the footer **“Frozen questions · Condition-blind answering · Unified report-level scoring”**. Use exact English text. Keep all text inside boxes. Avoid logos, extra labels, decorative characters, overlaps, cropped edges, and watermarks.
