# Survey Results Analysis

Students upload survey results as spreadsheet or CSV files. Counts, percentages, missing-answer checks, and charts are calculated by the app. Optional AI interpretations use only the columns students select and approve. No Google or Notion connection is needed for this module.

## Upload and check

1. Choose **Survey Results Analysis / 問卷結果分析** in the module dropdown.
2. Upload a `.csv`, `.xls`, or `.xlsx` file. Export the response table with question names in its first row, one response per subsequent row. For Excel, choose the worksheet containing responses.
3. Review the response count, column count, missing answers, and first 50 rows. CSV import controls support common encodings and separators.
4. Use each column's **Include** checkbox once to include or exclude it from both calculations and AI insights. Identifiers and timestamps start unchecked. Review every suggested question type: use **Number** for numerical answers, **Written feedback** for open responses, and **Checkbox** for multiple selections. Choose each checkbox question's in-cell separator.

Blank response rows are removed; duplicate rows are counted and retained because identical answers can come from different respondents. Blank or duplicate headers receive unique labels. Strings such as `NA` and numeric zero are preserved, not treated as missing. The limits are 20 MB uploaded, 20,000 response rows, 100 columns, and 150 MB expanded XLSX contents. Password-protected workbooks are unsupported.

Survey exports can join checkbox selections with commas. If an option itself contains a comma and the export does not quote individual options, the original selections cannot be reliably reconstructed by splitting commas. Inspect the distribution and prepare an unambiguous separator/export before relying on the results.

## Calculate measured findings

After reviewing the shared column selection, review the exact AI input and approve it. Click **Analyze results and generate AI insights** once to produce the calculated results and approved AI insights together. To calculate without AI, turn off **Include AI insights for the columns selected above**; the same button produces calculations and charts without an AI call or API key. If AI fails, the calculated results and downloads remain available.

- Single-choice counts and percentages use the nonblank answers as the answered denominator. A second percentage uses all response rows, including missing answers.
- Checkbox options count at most once per response. The denominator is the number of respondents with at least one parsed choice, not the number of selections. Percentages can sum to more than 100%.
- Numeric summaries distinguish valid numbers, nonnumeric entries, and missing answers. Zero remains a valid number. Mean, median, minimum, maximum, and histogram counts use valid finite numeric values. Histogram percentages use the valid-number count. Bins include their lower edge and exclude their upper edge, except the final bin includes both edges.
- Written-feedback results initially show answered/missing counts. Text is not sent to AI automatically.

The dashboard begins with a results-at-a-glance table. Choose any question to see its chart immediately, switch between counts and percentages, and inspect its full table. Charts display up to 20 categories for readability; distribution tables and downloads retain all categories. Chart toolbars can save PNG images.

Question comparison is hidden by default. Check **Show question comparison (optional)** to display its selectors, chart, and table. For questions with exact shared option labels, the chart shows answer shares side by side, with each question's answered denominator. This is useful for comparing broad consideration with a forced first choice; skip it when the questions are not meaningfully comparable. It does not establish individual preference changes. The comparison is included in downloads only while enabled.

The optional **Compare an answer across groups** section replaces the flow diagram. Enable it only when you have a specific comparison to explore. Select a single-choice grouping question, a separate single-choice result question, and one answer to compare. For example, compare how often each purchasing-frequency group chooses rice balls. A bar chart and table show the selected-answer count, valid group size, and percentage within each group. Groups with zero selections remain visible. Only responses answering both questions are used, and missing pairs are reported separately. Questions with more than 12 observed options are blocked for readability. Compare counts too, especially for small groups; differences do not establish statistical significance or causation. All calculations are unweighted descriptive findings from the uploaded sample, not estimates proven representative of the campus population.

## Approve optional AI input

1. Enter your chosen AI provider's API key in the sidebar if you want AI insights. Calculations, charts, and downloads work without it.
2. AI insights use the same **Include** column selection as the calculations. There is no second column-selection table. Excluded columns are not sent. The **Include AI insights** checkbox enables or disables AI for the entire selected set; it does not send anything until you approve the preview and click the action button.
3. Set the written-feedback sample size and insight language. The sample takes the first nonblank answers in file order, up to the selected maximum per column; it is not a random sample. Each answer is limited to 2,000 characters, with truncation and sample coverage shown in the payload.
4. Inspect **Exact AI input preview** and remove identifiers or sensitive information from the source file before approval. Selected categorical labels can also contain identifying text. The app does not promise automatic anonymization.
5. Approve sending the previewed input, then click **Analyze results and generate AI insights**. AI-input controls are available before the first analysis, so there is no separate generation button. Changing columns, language, provider, or feedback sample requires renewed approval. Payloads above 60,000 characters must be reduced before sending.

Optionally enter the decision you want to support, such as which product to pilot. AI results now form a concise decision brief: up to four key findings with practical implications, up to six grouped feedback themes, and up to three actions with suggested pilot measures. The theme chart shows AI-cited supporting examples; it does not claim full-population theme prevalence. Currency is displayed as ordinary text, including prices such as NT$40–59.

General AI insights use question-based headings, with the actual result underneath: for example, **Top Single-add Food Choice**, **Top Food Interest (Select All)**, and **Preferred Time Window**. **Top Open-ended Food Interest** applies only to written comments. **Average Price** is appropriate for numeric price answers; category ranges instead use **Preferred Price Range**, without inventing an average. Titles adapt to the survey subject and selected language. Action headings belong in recommendations.

Measured findings remain separate from AI interpretations. Every AI entry must cite an existing evidence ID. The main view hides technical references inside supporting-data expanders rather than repeating them beneath every sentence. The app checks reference existence and calculates the number of unique cited sample answers for themes. It does not verify that the model's interpretation, theme assignment, or every numeric statement is correct; students must compare statements with their supporting data.

If the AI returns malformed output or unknown evidence IDs, the app requests one correction from the same provider using the same approved input. Cosmetic reference formatting is normalized without guessing IDs. If correction fails, an analysis-validation error identifies the section and failed reference; calculated findings remain available. No written-feedback themes are generated when no written-feedback answers were selected.

Theme example counts describe AI-selected supporting answers within the shared sample. They are not measured prevalence percentages for all respondents. A theme spanning multiple questions can cite multiple answers from one respondent. Sample feedback IDs map to the nonblank response-row order; source blank rows are excluded from that numbering.

## Turn recommendations into a marketing plan

Below **Recommended next steps**, click **Use recommendations in Marketing Promotion**. The app opens **Marketing promotion → Survey action & promotion plan** with the recommendations and their supporting measured evidence. Raw written-feedback answers and API keys are not transferred into the plan brief.

Review or edit the imported recommendations, then add the business/product, audience, objective, timing, resources, and promotion channels. Click **Generate action and promotion plan** using the selected sidebar AI provider. The written plan includes prioritized tasks, a promotion strategy and draft channel content, an implementation schedule, measures for the pilot, and assumptions needing confirmation. Proposed prices or offers are not treated as approved commitments.

Edit the generated plan and confirm review before clicking **Save plan to Notion**. Use the existing sidebar Notion key and parent page link. The plan is saved as a child page under that parent, and the app shows its direct link. Retrying the same reviewed plan reuses a completed save; a changed plan creates a separate version rather than overwriting an existing page. Editing the input brief requires regeneration before saving. Form values and edited plan text are retained within the current Streamlit session when switching modules.

Long plans are saved in batches within Notion's block-count and request-size limits. If a save is interrupted, retry the same title and plan: the app reads the saved blocks and resumes from the missing content, including when an append succeeded but its response was lost. A partial-page link is shown when available. The app verifies the full content before reporting completion and refuses to overwrite a page that was modified outside the app.

Saving converts Markdown into native Notion headings, bold and italic text, links, numbered/bullet lists, dividers, and schedule tables. Markdown markers such as `**` and table pipes are not displayed as formatting syntax. Saving a plan previously created with the plain-text formatter creates a new formatted version; its earlier page remains intact. Deploy the updated `marketing_plan.py` and `requirements.txt` so the Markdown parser dependency is available on the hosted app.

中文流程：在「建議下一步」點選「將建議用於行銷推廣」→檢查建議並補上受眾、時程、資源及渠道→產生行動與推廣計畫→編輯及確認→使用側欄 Notion 設定儲存為上層頁面下的子頁面，並開啟回傳連結。

## Download

Download the ZIP with:

- `analysis_and_charts.html`: an offline HTML report with measured tables and interactive charts; includes AI results and supporting evidence when current approved results exist.
- `analysis.json`: the measured results, numeric bin boundaries, method notes, and any current AI interpretations and evidence scope.
- `distributions.csv`: counts, percentages, and denominators, including all categories.
- `data_checks.csv`: answered/missing counts for every imported column.
- `highlights.csv`: the results-at-a-glance table. When displayed, `question_comparison.csv` and `group_comparison.csv` contain the underlying comparison tables. The group comparison includes counts, valid group sizes, and percentages for the chosen answer. The offline HTML report includes these charts and the readable AI finding cards, theme chart, and action table.
- `README.txt`: instructions and denominator notes.

Raw uploaded response rows and the raw written-feedback list are excluded from the report bundle. Category names and AI-generated text, which may quote selected answers, remain in reports, so review them before sharing. Changing the file, worksheet, import settings, or analysis column settings invalidates earlier results. Changing AI input hides earlier AI output from both the page and downloads until insights are generated for the current input.

## 中文學生流程

1. 選擇「問卷結果分析」，上傳 CSV、XLS 或 XLSX 問卷結果。Excel 檔請選擇回覆所在的工作表。
2. 檢查回覆數、欄位、未回答及預覽。每欄只需勾選一次「包含」，即同時用於計算與 AI 洞察；排除姓名、電子郵件、學號、時間戳記等欄位，檢查題型與複選分隔符號。檢查完整 AI 輸入並同意傳送後，按一次「分析結果並產生 AI 洞察」。如僅需計算與圖表，可取消「為上方所選欄位產生 AI 洞察」，不呼叫 AI。
3. 查看由應用程式計算的實測結果與圖表，注意分母：複選比例以有回答該題的人數為分母，總和可能超過 100%；數字統計只使用有效數值，空白不視為零。
4. AI 洞察沿用上方同一組欄位，不需要再選一次。設定文字樣本筆數及語言，檢查完整輸入並同意後才送出；未勾選「包含」的欄位不會傳送給模型。
5. 對照支持數字檢查 AI 的偏好詮釋、文字主題與建議。主題例數只表示引用樣本，不代表全體填答者的比例。下載 ZIP 報告、表格及圖表。

## Deployment

Upload the updated `app.py`, `survey_analysis.py`, new `marketing_plan.py`, and updated `requirements.txt` to the repository used by Streamlit. Keep `customer_service.py` and other required app files. Install the updated dependencies before running locally. The previous Survey Builder, prompt exporter, and their setup guide have been removed. Marketing Promotion now offers its original promotion-content workflow and the survey action/promotion-plan workflow; the other modules retain their existing workflows.
