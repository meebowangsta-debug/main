import json
import base64
from io import BytesIO
from PIL import Image, ImageOps
import time
from urllib.parse import urlparse

import httpx
import streamlit as st
from openai import OpenAI
from google import genai
from anthropic import Anthropic
from notion_client import Client
from survey_analysis import render_survey_analysis
from campaign_analysis import render_campaign_analysis
from competitor_analysis import render_competitor_analysis
from marketing_plan import render_marketing_plan, COPY_WORKFLOW, PLAN_WORKFLOW, digest
from customer_service import load_knowledge, service_reply, save_ticket, new_reference, DEFAULT_MODELS, test_service_connection, service_connection_error, service_error_details, cursor_reply, select_text_model, dated_notion_title
import hashlib


IMAGE_MODELS = {"OpenAI": "gpt-image-1.5", "Gemini": "gemini-2.5-flash-image"}


def reset_module_fields(module):
    """Reset only the selected workspace; connection settings and other modules survive."""
    prefixes = {
        "Marketing promotion | 行銷推廣": ("copy_", "marketing_plan_"),
        "Branding & image | 品牌與圖片": ("brand_",),
        "Customer Service | 顧客服務": ("support_",),
        "Survey Results Analysis | 問卷結果分析": ("survey_",),
        "Campaign Performance Analysis | 行銷成效分析": ("campaign_",),
        "Competitor Analysis | 競爭者分析": ("competitor_",),
    }[module]
    for key in list(st.session_state):
        if key.startswith(prefixes) and key != "support_knowledge":
            del st.session_state[key]
    if module == "Marketing promotion | 行銷推廣":
        st.session_state.pop("output", None)
    # New upload widget identities also discard browser-held file selections.
    generations = dict(st.session_state.get("module_reset_generations", {}))
    generations[module] = generations.get(module, 0) + 1
    st.session_state.module_reset_generations = generations
    if module == "Customer Service | 顧客服務":
        st.session_state.support_messages = []


def generate_branding_image(provider, api_key, prompt, aspect_ratio):
    if provider not in IMAGE_MODELS:
        raise ValueError("Choose OpenAI or Gemini for image generation. | 請選擇 OpenAI 或 Gemini 產生圖片。")
    if provider == "OpenAI":
        size = "1024x1024" if aspect_ratio == "1:1" else (
            "1536x1024" if aspect_ratio == "16:9" else "1024x1536"
        )
        response = OpenAI(api_key=api_key, timeout=180.0, max_retries=0).images.generate(
            model=IMAGE_MODELS[provider], prompt=prompt, size=size, n=1,
            output_format="png",
        )
        if not response.data or not response.data[0].b64_json:
            raise ValueError("No image was returned. Please try a different prompt.")
        data = base64.b64decode(response.data[0].b64_json)
    else:
        with genai.Client(api_key=api_key, http_options={"timeout": 180000}) as client:
            response = client.models.generate_content(
                model=IMAGE_MODELS[provider], contents=prompt,
                config={"response_modalities": ["TEXT", "IMAGE"],
                        "image_config": {"aspect_ratio": aspect_ratio}},
            )
        data = None
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else []) or []:
                if part.inline_data and (part.inline_data.mime_type or "").startswith("image/"):
                    data = part.inline_data.data
                    break
            if data:
                break
        if not data:
            raise ValueError("No image was returned. The request may have been blocked; try revising the prompt. | 未收到圖片，請調整提示詞後重試。")
    # Export the exact requested ratio, including ratios the OpenAI API cannot output natively.
    with Image.open(BytesIO(data)) as image:
        width_ratio, height_ratio = map(int, aspect_ratio.split(":"))
        unit = min(image.width // width_ratio, image.height // height_ratio)
        image = ImageOps.fit(image.convert("RGB"), (unit * width_ratio, unit * height_ratio))
        output = BytesIO()
        image.save(output, format="PNG")
    return output.getvalue()


def upload_notion_image(notion, api_key, data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Image exceeds Notion's 20 MB upload limit. Download it and resize before saving.")
    upload = notion.file_uploads.create(mode="single_part", filename="branding.png", content_type="image/png")
    response = httpx.post(
        f"https://api.notion.com/v1/file_uploads/{upload['id']}/send",
        headers={"Authorization": f"Bearer {api_key}", "Notion-Version": "2025-09-03"},
        files={"file": ("branding.png", data, "image/png")}, timeout=120.0,
    )
    response.raise_for_status()
    if response.json().get("status") != "uploaded":
        raise ValueError("Notion image upload did not finish. Please retry saving.")
    return [{"name": "branding.png", "type": "file_upload", "file_upload": {"id": upload["id"]}}]


def show_copyable_error(error, provider, model, api_key):
    details = service_error_details(error, provider, model, api_key)
    report = service_connection_error(error) + "\n\n" + json.dumps(details, ensure_ascii=False, indent=2)
    st.caption("Copy error: click the copy icon at the top-right of the report below. | 複製錯誤：點擊下方報告右上角的複製圖示。")
    st.code(report, language=None, wrap_lines=True)


def test_openai_connection(api_key):
    client = OpenAI(api_key=api_key)
    client.models.list()


def test_gemini_connection(api_key):
    client = genai.Client(api_key=api_key)
    next(iter(client.models.list(config={"page_size": 1})), None)


def test_claude_connection(api_key):
    client = Anthropic(api_key=api_key)
    client.models.list(limit=1)


CURSOR_API_BASE = "https://api.cursor.com"


def test_cursor_connection(api_key):
    response = httpx.get(
        f"{CURSOR_API_BASE}/v1/models",
        auth=(api_key.strip(), ""),
        timeout=30.0,
    )
    response.raise_for_status()


def test_notion_connection(api_key, database_id):
    notion = Client(auth=api_key)
    database = notion.databases.retrieve(database_id=database_id.strip())
    title_parts = database.get("title", [])
    name = "".join(part.get("plain_text", "") for part in title_parts).strip()
    return name or "Untitled"


st.set_page_config(
    page_title="Multi-Model AI Marketing Bot",
    page_icon="🎯",
    layout="centered"
)


def build_prompt(
    product_name,
    product_description,
    promotion_type,
    target_audience,
    message_tone,
    time_frame
):
    return f"""
You are an AI marketing agent.

Create marketing content for this promotion.

Product Name: {product_name}
Product Description: {product_description}
Promotion Type: {promotion_type}
Target Audience: {target_audience}
Message Tone: {message_tone}
Time Frame of Promotion: {time_frame}

Return JSON only with exactly these fields:
{{
  "ig_caption": "",
  "tiktok_script": "",
  "hashtags": "",
  "brief_email_content": ""
}}

Rules:
1. IG Caption should be engaging and concise.
2. TikTok Script should include scene/action ideas.
3. Hashtags should be one string separated by spaces.
4. Brief Email Content should include a subject line and short body.
5. Do not include markdown code fences.
"""


def generate_with_openai(api_key, prompt):
    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=select_text_model("OpenAI", api_key),
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "marketing_content",
                "schema": {
                    "type": "object",
                    "properties": {
                        "ig_caption": {"type": "string"},
                        "tiktok_script": {"type": "string"},
                        "hashtags": {"type": "string"},
                        "brief_email_content": {"type": "string"}
                    },
                    "required": [
                        "ig_caption",
                        "tiktok_script",
                        "hashtags",
                        "brief_email_content"
                    ],
                    "additionalProperties": False
                },
                "strict": True
            }
        }
    )

    return json.loads(response.output_text)


def generate_with_gemini(api_key, prompt):
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=select_text_model("Gemini", api_key),
        contents=prompt
    )

    text = response.text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def generate_with_claude(api_key, prompt):
    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=select_text_model("Claude", api_key),
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def generate_with_cursor(api_key, prompt):
    text = cursor_reply(api_key, DEFAULT_MODELS["Cursor"], [{"role": "user", "content": prompt}])
    return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())


NOTION_MARKETING_COPY_COLUMNS = {
    "English": {
        "product_name": "Product Name",
        "product_description": "Product Description",
        "promotion_type": "Promotion Type",
        "target_audience": "Target Audience",
        "message_tone": "Message Tone",
        "time_frame": "Time Frame",
        "ai_model": "AI Model",
        "ig_caption": "IG Caption",
        "tiktok_script": "TikTok Script",
        "hashtags": "Hashtags",
        "brief_email_content": "Brief Email Content",
    },
    "Traditional Chinese | 繁體中文": {
        "product_name": "產品名稱",
        "product_description": "產品描述",
        "promotion_type": "推廣類型",
        "target_audience": "目標受眾",
        "message_tone": "文案風格",
        "time_frame": "推廣時間段",
        "ai_model": "AI 模型",
        "ig_caption": "IG 文案",
        "tiktok_script": "TikTok 腳本",
        "hashtags": "話題標籤",
        "brief_email_content": "郵件內容",
    },
}


NOTION_BRANDING_IMAGE_COLUMNS = {
    "English": {
        "product_name": "Product Name",
        "business_type": "Business Type",
        "brand_name": "Brand Name",
        "product_description": "Product Description",
        "visual_details": "Visual Details",
        "brand_colors": "Brand Colors",
        "visual_style": "Visual Style",
        "scene": "Scene",
        "mascot_or_theme": "Mascot or Theme",
        "image_purpose": "Image Purpose",
        "aspect_ratio": "Aspect Ratio",
        "headline": "Headline",
        "subhead": "Subhead",
        "overlay_language": "Overlay Language",
        "avoid": "Avoid in Image",
        "ai_model": "AI Model",
        "image_prompt": "Image Prompt",
        "image": "Image",
    },
    "Traditional Chinese | 繁體中文": {
        "product_name": "產品名稱",
        "business_type": "業態類型",
        "brand_name": "品牌名稱",
        "product_description": "產品描述",
        "visual_details": "視覺重點",
        "brand_colors": "品牌色",
        "visual_style": "視覺風格",
        "scene": "場景氛圍",
        "mascot_or_theme": "吉祥物或主題",
        "image_purpose": "圖片用途",
        "aspect_ratio": "比例",
        "headline": "主標",
        "subhead": "副標",
        "overlay_language": "文字語言",
        "avoid": "避免出現",
        "ai_model": "AI 模型",
        "image_prompt": "圖片提示詞",
        "image": "圖片",
    },
}

NOTION_DATABASE_TITLES = {
    "English": {
        "marketing_copy": "AI Marketing Copy",
        "branding_images": "AI Branding Images",
    },
    "Traditional Chinese | 繁體中文": {
        "marketing_copy": "AI 行銷文案",
        "branding_images": "AI 品牌圖片",
    },
}


def parse_notion_id(value):
    raw = (value or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host in {"notion.so", "notion.site", "notion.com", "app.notion.com"} or host.endswith((".notion.so", ".notion.site")):
        slug = parsed.path.rstrip("/").split("/")[-1]
        compact = slug.replace("-", "")
        if len(compact) >= 32:
            raw = compact[-32:]
        else:
            raw = slug
    return raw.replace("-", "")


def test_notion_parent_page(api_key, parent_page_id):
    notion = Client(auth=api_key)
    page = notion.pages.retrieve(page_id=parse_notion_id(parent_page_id))
    title_prop = page.get("properties", {})
    for prop in title_prop.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            name = "".join(part.get("plain_text", "") for part in parts).strip()
            return name or "Untitled"
    return "Untitled"


def _marketing_copy_db_schema(column_names):
    c = column_names
    return {
        c["product_name"]: {"title": {}},
        c["product_description"]: {"rich_text": {}},
        c["promotion_type"]: {"rich_text": {}},
        c["target_audience"]: {"rich_text": {}},
        c["message_tone"]: {"rich_text": {}},
        c["time_frame"]: {"rich_text": {}},
        c["ai_model"]: {"rich_text": {}},
        c["ig_caption"]: {"rich_text": {}},
        c["tiktok_script"]: {"rich_text": {}},
        c["hashtags"]: {"rich_text": {}},
        c["brief_email_content"]: {"rich_text": {}},
    }


def _branding_image_db_schema(column_names):
    c = column_names
    return {
        c["product_name"]: {"title": {}},
        c["business_type"]: {"rich_text": {}},
        c["brand_name"]: {"rich_text": {}},
        c["product_description"]: {"rich_text": {}},
        c["visual_details"]: {"rich_text": {}},
        c["brand_colors"]: {"rich_text": {}},
        c["visual_style"]: {"rich_text": {}},
        c["scene"]: {"rich_text": {}},
        c["mascot_or_theme"]: {"rich_text": {}},
        c["image_purpose"]: {"rich_text": {}},
        c["aspect_ratio"]: {"rich_text": {}},
        c["headline"]: {"rich_text": {}},
        c["subhead"]: {"rich_text": {}},
        c["overlay_language"]: {"rich_text": {}},
        c["avoid"]: {"rich_text": {}},
        c["ai_model"]: {"rich_text": {}},
        c["image_prompt"]: {"rich_text": {}},
        c["image"]: {"files": {}},
    }


def create_marketing_copy_database(api_key, parent_page_id, notion_column_language):
    notion = Client(auth=api_key)
    cols = NOTION_MARKETING_COPY_COLUMNS[notion_column_language]
    titles = NOTION_DATABASE_TITLES[notion_column_language]
    created = notion.databases.create(
        parent={"type": "page_id", "page_id": parse_notion_id(parent_page_id)},
        title=[{"type": "text", "text": {"content": titles["marketing_copy"]}}],
        initial_data_source={"properties": _marketing_copy_db_schema(cols)},
    )
    return created["id"]


def create_branding_images_database(api_key, parent_page_id, notion_column_language):
    notion = Client(auth=api_key)
    cols = NOTION_BRANDING_IMAGE_COLUMNS[notion_column_language]
    titles = NOTION_DATABASE_TITLES[notion_column_language]
    created = notion.databases.create(
        parent={"type": "page_id", "page_id": parse_notion_id(parent_page_id)},
        title=[{"type": "text", "text": {"content": titles["branding_images"]}}],
        initial_data_source={"properties": _branding_image_db_schema(cols)},
    )
    return created["id"]


def prepare_notion_data_source(notion, database_id, schema):
    database = notion.databases.retrieve(database_id=database_id)
    sources = database.get("data_sources", [])
    if len(sources) != 1:
        raise ValueError("Expected one data source in this database. Please select a database with a single data source.")
    source_id = sources[0]["id"]
    source = notion.data_sources.retrieve(data_source_id=source_id)
    properties = source.get("properties", {})
    updates = {}
    for name, definition in schema.items():
        expected_type = next(iter(definition))
        if name in properties:
            if properties[name].get("type") != expected_type:
                raise ValueError(f"Notion column '{name}' must have type '{expected_type}'.")
            continue
        if expected_type == "title":
            title = next((prop for prop in properties.values() if prop.get("type") == "title"), None)
            if title:
                updates[title["id"]] = {"name": name}
                continue
        updates[name] = definition
    if updates:
        notion.data_sources.update(data_source_id=source_id, properties=updates)
    return source_id


def show_notion_database_link(database_id):
    url = f"https://www.notion.so/{parse_notion_id(database_id)}"
    st.markdown(f"[Open in Notion | 在 Notion 開啟]({url})")


def show_created_database_details(database_id, notion_column_language, database_type):
    database_name = NOTION_DATABASE_TITLES[notion_column_language][database_type]
    st.write(f"Database name | 資料庫名稱：{database_name}")
    st.caption("Database ID | 資料庫 ID")
    st.code(database_id, language=None)
    show_notion_database_link(database_id)


def find_existing_database(api_key, parent_page_id, notion_column_language, database_type):
    notion = Client(auth=api_key)
    preferred_title = NOTION_DATABASE_TITLES[notion_column_language][database_type]
    known_titles = {titles[database_type] for titles in NOTION_DATABASE_TITLES.values()}
    matches = []
    cursor = None
    while True:
        params = {"block_id": parse_notion_id(parent_page_id), "page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        result = notion.blocks.children.list(**params)
        for block in result.get("results", []):
            if block.get("type") != "child_database" or block.get("archived") or block.get("in_trash"):
                continue
            title = block["child_database"].get("title", "")
            if title in known_titles:
                matches.append((title, block["id"]))
        if not result.get("has_more"):
            break
        cursor = result["next_cursor"]
    # Prefer the selected language, while also reusing an existing database
    # if the student changed the column-language setting.
    matches.sort(key=lambda match: match[0] != preferred_title)
    return matches[0][1] if matches else None


def ensure_marketing_copy_database(
    api_key, parent_page_id, notion_column_language, database_id
):
    existing = (database_id or "").strip()
    if existing:
        return existing, False
    if not (api_key or "").strip() or not (parent_page_id or "").strip():
        raise ValueError(
            "Notion API key and parent page link are required. | "
            "需要 Notion 金鑰與商家頁面連結。"
        )
    test_notion_parent_page(api_key, parent_page_id)
    found = find_existing_database(
        api_key, parent_page_id, notion_column_language, "marketing_copy"
    )
    if found:
        return found, False
    return (
        create_marketing_copy_database(
            api_key, parent_page_id, notion_column_language
        ),
        True,
    )


def ensure_branding_images_database(
    api_key, parent_page_id, notion_column_language, database_id
):
    existing = (database_id or "").strip()
    if existing:
        return existing, False
    if not (api_key or "").strip() or not (parent_page_id or "").strip():
        raise ValueError(
            "Notion API key and parent page link are required. | "
            "需要 Notion 金鑰與商家頁面連結。"
        )
    test_notion_parent_page(api_key, parent_page_id)
    found = find_existing_database(
        api_key, parent_page_id, notion_column_language, "branding_images"
    )
    if found:
        return found, False
    return (
        create_branding_images_database(
            api_key, parent_page_id, notion_column_language
        ),
        True,
    )


def build_branding_image_prompt(
    business_type,
    brand_name,
    brand_product_name,
    brand_product_description,
    brand_visual_details,
    brand_colors,
    visual_style,
    scene_vibe,
    mascot_or_theme,
    image_purpose,
    aspect_ratio,
    include_text_on_image,
    image_headline,
    image_subhead,
    overlay_language,
    avoid_in_image,
):
    lines = [
        f"Business type: {business_type}",
        f"Brand: {brand_name or 'N/A'}",
        f"Product: {brand_product_name}",
        f"Description: {brand_product_description}",
        f"Visual details: {brand_visual_details}",
        f"Brand colors: {brand_colors or 'N/A'}",
        f"Style: {visual_style}",
        f"Scene: {scene_vibe or 'N/A'}",
        f"Mascot/theme: {mascot_or_theme or 'N/A'}",
        f"Purpose: {image_purpose}",
        f"Aspect ratio: {aspect_ratio}",
    ]
    if include_text_on_image:
        lines.append(
            f"On-image text ({overlay_language}): headline={image_headline}, "
            f"subhead={image_subhead}"
        )
    if avoid_in_image:
        lines.append(f"Avoid: {avoid_in_image}")
    return "\n".join(lines)


def database_save_identity(prefix,notion,source_id,title_property,title,payload,api_key):
    signature=digest([source_id,title_property,title,payload,hashlib.sha256(api_key.encode()).hexdigest()])
    state_key=prefix+"_notion_identity"
    identity=st.session_state.get(state_key)
    if not identity or identity['signature']!=signature:
        identity={'signature':signature,'title':dated_notion_title(title)}
        st.session_state[state_key]=identity
    existing=notion.data_sources.query(data_source_id=source_id,
        filter={'property':title_property,'title':{'equals':identity['title']}},page_size=1).get('results',[])
    return identity['title'],existing[0] if existing else None


def save_branding_to_notion(
    notion_api_key,
    notion_database_id,
    notion_column_language,
    ai_model,
    brand_product_name,
    business_type,
    brand_name,
    brand_product_description,
    brand_visual_details,
    brand_colors,
    visual_style,
    scene_vibe,
    mascot_or_theme,
    image_purpose,
    aspect_ratio,
    image_headline,
    image_subhead,
    overlay_language,
    avoid_in_image,
    image_prompt,
    image_data=None,
):
    cols = NOTION_BRANDING_IMAGE_COLUMNS[notion_column_language]
    notion = Client(auth=notion_api_key)

    source_id = prepare_notion_data_source(
        notion, notion_database_id, _branding_image_db_schema(cols)
    )
    title,existing=database_save_identity('brand',notion,source_id,cols['product_name'],brand_product_name,
        [ai_model,business_type,brand_name,brand_product_description,brand_visual_details,brand_colors,visual_style,
         scene_vibe,mascot_or_theme,image_purpose,aspect_ratio,image_headline,image_subhead,overlay_language,
         avoid_in_image,image_prompt,hashlib.sha256(image_data or b'').hexdigest()],notion_api_key)
    if existing:return existing
    image_files = upload_notion_image(notion, notion_api_key, image_data) if image_data else []
    return notion.pages.create(
        parent={"type": "data_source_id", "data_source_id": source_id},
        properties={
            cols["product_name"]: {
                "title": [{"text": {"content": title}}]
            },
            cols["business_type"]: {
                "rich_text": notion_rich_text(business_type)
            },
            cols["brand_name"]: {"rich_text": notion_rich_text(brand_name)},
            cols["product_description"]: {
                "rich_text": notion_rich_text(brand_product_description)
            },
            cols["visual_details"]: {
                "rich_text": notion_rich_text(brand_visual_details)
            },
            cols["brand_colors"]: {"rich_text": notion_rich_text(brand_colors)},
            cols["visual_style"]: {"rich_text": notion_rich_text(visual_style)},
            cols["scene"]: {"rich_text": notion_rich_text(scene_vibe)},
            cols["mascot_or_theme"]: {
                "rich_text": notion_rich_text(mascot_or_theme)
            },
            cols["image_purpose"]: {"rich_text": notion_rich_text(image_purpose)},
            cols["aspect_ratio"]: {"rich_text": notion_rich_text(aspect_ratio)},
            cols["headline"]: {"rich_text": notion_rich_text(image_headline)},
            cols["subhead"]: {"rich_text": notion_rich_text(image_subhead)},
            cols["overlay_language"]: {
                "rich_text": notion_rich_text(overlay_language)
            },
            cols["avoid"]: {"rich_text": notion_rich_text(avoid_in_image)},
            cols["ai_model"]: {"rich_text": notion_rich_text(ai_model)},
            cols["image_prompt"]: {"rich_text": notion_rich_text(image_prompt)},
            cols["image"]: {"files": image_files},
        },
    )


def notion_rich_text(content):
    text = content if content is not None else ""
    if not text:
        return [{"text": {"content": ""}}]
    return [
        {"text": {"content": text[i : i + 2000]}}
        for i in range(0, len(text), 2000)
    ]


def save_to_notion(
    notion_api_key,
    notion_database_id,
    notion_column_language,
    ai_model,
    product_name,
    product_description,
    promotion_type,
    target_audience,
    message_tone,
    time_frame,
    output,
):
    cols = NOTION_MARKETING_COPY_COLUMNS[notion_column_language]
    notion = Client(auth=notion_api_key)

    source_id = prepare_notion_data_source(
        notion, notion_database_id, _marketing_copy_db_schema(cols)
    )
    title,existing=database_save_identity('copy',notion,source_id,cols['product_name'],product_name,
        [ai_model,product_description,promotion_type,target_audience,message_tone,time_frame,output],notion_api_key)
    if existing:return existing
    return notion.pages.create(
        parent={"type": "data_source_id", "data_source_id": source_id},
        properties={
            cols["product_name"]: {
                "title": [{"text": {"content": title}}]
            },
            cols["product_description"]: {
                "rich_text": notion_rich_text(product_description)
            },
            cols["promotion_type"]: {
                "rich_text": notion_rich_text(promotion_type)
            },
            cols["target_audience"]: {
                "rich_text": notion_rich_text(target_audience)
            },
            cols["message_tone"]: {
                "rich_text": notion_rich_text(message_tone)
            },
            cols["time_frame"]: {
                "rich_text": notion_rich_text(time_frame)
            },
            cols["ai_model"]: {
                "rich_text": notion_rich_text(ai_model)
            },
            cols["ig_caption"]: {
                "rich_text": notion_rich_text(output["ig_caption"])
            },
            cols["tiktok_script"]: {
                "rich_text": notion_rich_text(output["tiktok_script"])
            },
            cols["hashtags"]: {
                "rich_text": notion_rich_text(output["hashtags"])
            },
            cols["brief_email_content"]: {
                "rich_text": notion_rich_text(output["brief_email_content"])
            },
        },
    )


st.title("🎯 Multi-Model AI Marketing Bot")
st.write(
    "Choose OpenAI, Gemini, Claude, or Cursor, generate marketing content, "
    "and save it to Notion. | 選擇 AI 模型（含 Cursor），產生行銷內容，並儲存到 Notion。"
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] :is(.st-key-ai_provider, [class*="st-key-ai_api_key_"],
        .st-key-notion_api_key, .st-key-notion_parent_page_id)
        [data-testid="stWidgetLabel"] p {
        color: #ffffff !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("AI Model Settings | AI 模型設定")

    ai_provider = st.selectbox(
        "Choose AI Provider | 選擇 AI 供應商",
        ["OpenAI", "Gemini", "Grok", "Claude", "Cursor"],
        key="ai_provider",
    )

    ai_api_key = st.text_input(
        f"{ai_provider} API Key | {ai_provider} 金鑰",
        type="password",
        key=f"ai_api_key_{ai_provider}",
        help=(
            "Cursor: use your key from Cursor Dashboard → Integrations. | "
            "Cursor：請在 Cursor 控制台 → Integrations 取得金鑰。"
            if ai_provider == "Cursor"
            else None
        ),
    )

    if st.button(f"Test {ai_provider} Connection | 測試連線"):
        if not ai_api_key:
            st.warning(f"Enter your {ai_provider} API key first. | 請先輸入 {ai_provider} 金鑰。")
        else:
            with st.spinner("Testing... | 測試中..."):
                try:
                    test_service_connection(ai_provider, ai_api_key.strip())
                    st.success(f"{ai_provider} connection successful! | 連線成功！")
                except Exception as error:
                    st.error(service_connection_error(error))
                    with st.expander("Connection error details | 連線錯誤詳細資訊", expanded=True):
                        show_copyable_error(error, ai_provider, DEFAULT_MODELS[ai_provider], ai_api_key)
                        st.caption("This test checks the API connection only. Model availability and generation credits are checked when you send a message. | 此測試僅檢查 API 連線，模型是否可用及生成額度會在傳送訊息時確認。")

    st.header("Notion Settings | Notion 設定")

    st.caption(
        "Use one page for business knowledge and support tickets. Connect it to your Notion integration. | "
        "使用同一頁放商家知識與客服工單，並將頁面連接至 Notion 整合。"
    )

    notion_api_key = st.text_input(
        "Notion API Key | Notion 金鑰",
        type="password",
        key="notion_api_key",
    )

    notion_parent_page_id = st.text_input(
        "Notion business page link | Notion 商家頁面連結",
        placeholder="https://www.notion.so/My-page-0123456789abcdef0123456789abcdef",
        help=(
            "Put your business information directly on this page. The bot reads its text and tables; "
            "ticket databases are created or reused underneath. Subpages are not loaded automatically. | "
            "將商家資訊直接寫在此頁面，機器人讀取文字與表格，並在頁面下建立或重用工單資料庫。子頁面不會自動載入。"
        ),
        key="notion_parent_page_id",
    )

    test_notion_clicked = st.button("Test Notion page connection | 測試 Notion 頁面連線", key="btn_test_parent_page")
    if test_notion_clicked:
        if not notion_api_key.strip() or not notion_parent_page_id.strip():
            st.warning(
                "Enter your Notion API key and paste the business page link first. | "
                "請先輸入 Notion 金鑰並貼上商家頁面連結。"
            )
        else:
            with st.spinner("Testing page connection... | 測試頁面連線中..."):
                try:
                    page_name = test_notion_parent_page(
                        notion_api_key, notion_parent_page_id
                    )
                    st.success(
                        f'Connected to page: "{page_name}" | 已連線至頁面：「{page_name}」'
                    )
                except Exception as e:
                    st.error(
                        "Could not connect to the Notion page. Check the API key and "
                        "page link, and share the page with your integration. | "
                        "無法連線至 Notion 頁面。請檢查金鑰與頁面連結，並將頁面分享給整合。"
                    )
                    st.caption(str(e))

    with st.expander("Advanced: separate knowledge page | 進階：使用不同知識頁面"):
        separate_knowledge = st.checkbox("Use a different knowledge page | 使用不同的知識頁面", key="use_separate_knowledge")
        separate_link = st.text_input(
            "Separate knowledge page link | 另一個知識頁面連結",
            key="service_knowledge_link", disabled=not separate_knowledge,
            help="Connect this page to the same Notion integration. | 請將此頁面連接至相同的 Notion 整合。",
        )
    knowledge_link = separate_link if separate_knowledge else notion_parent_page_id
    scope = (parse_notion_id(knowledge_link), parse_notion_id(notion_parent_page_id), notion_api_key)
    if st.session_state.get("service_scope") != scope:
        for state_key in list(st.session_state):
            if state_key.startswith("support_"):
                del st.session_state[state_key]
        st.session_state.service_scope = scope
        st.session_state.service_knowledge_attempted = False
        st.session_state.service_knowledge_error = False
        st.session_state.pop("service_knowledge_details", None)
    st.session_state.setdefault("support_messages", [])
    refresh_knowledge = st.button("Refresh business knowledge | 更新商家知識", key="btn_load_knowledge")
    auto_load_knowledge = (
        bool(notion_api_key.strip() and knowledge_link.strip())
        and not st.session_state.get("support_knowledge")
        and (not st.session_state.get("service_knowledge_error") or test_notion_clicked)
    )
    if refresh_knowledge or auto_load_knowledge:
        # Clear stale knowledge and chat before attempting refresh.
        for state_key in list(st.session_state):
            if state_key.startswith("support_"):
                del st.session_state[state_key]
        st.session_state.support_messages = []
        if not notion_api_key.strip() or not knowledge_link.strip():
            st.warning("Enter the Notion key and business page link. | 請輸入 Notion 金鑰與商家頁面連結。")
        else:
            st.session_state.service_knowledge_attempted = True
            st.session_state.service_knowledge_error = False
            try:
                with st.spinner("Loading knowledge... | 正在載入知識..."):
                    st.session_state.support_knowledge = load_knowledge(notion_api_key.strip(), parse_notion_id(knowledge_link))
            except Exception as error:
                st.session_state.service_knowledge_error = True
                st.session_state.service_knowledge_details = service_error_details(
                    error, "Notion", "Business page text", notion_api_key
                )
    if st.session_state.get("service_knowledge_error"):
        st.error("Knowledge could not be loaded. Check the Notion key, page access, and readable page text, then click Refresh business knowledge to retry. | 無法載入知識，請檢查 Notion 金鑰、頁面權限與文字內容，再按「更新商家知識」重試。")
    if st.session_state.get("support_knowledge"):
        st.caption("Business knowledge loaded | 商家知識已載入：" + st.session_state.support_knowledge["title"])

    notion_column_language = st.selectbox(
        "Notion column names | Notion 欄位名稱",
        list(NOTION_MARKETING_COPY_COLUMNS.keys()),
        help=(
            "Language used when creating databases and when saving rows. "
            "繁體中文：title column is「產品名稱」. | "
            "建立資料庫與儲存時使用同一套欄位語言。"
        ),
        key="notion_column_language",
    )

    st.session_state.setdefault("marketing_copy_database_id", "")
    st.session_state.setdefault("branding_images_database_id", "")

    st.caption(
        "No database IDs needed: existing databases on your page are reused; missing ones are created automatically. | "
        "無需填寫資料庫 ID：會重用頁面上的既有資料庫，找不到時才自動建立。"
    )
    with st.expander("Advanced: use existing databases | 進階：使用既有資料庫"):
        marketing_db_input = st.text_input(
            "Marketing copy database ID | 行銷文案資料庫 ID",
            value=st.session_state.marketing_copy_database_id,
            help="Filled in after your first save. | 首次儲存後自動填入。",
        )
        st.session_state.marketing_copy_database_id = marketing_db_input.strip()

        branding_db_input = st.text_input(
            "Branding images database ID | 品牌圖片資料庫 ID",
            value=st.session_state.branding_images_database_id,
            help="Filled in after your first save. | 首次儲存後自動填入。",
        )
        st.session_state.branding_images_database_id = branding_db_input.strip()


selected_module = st.selectbox(
    "Choose a module | 選擇模組",
    ["Survey Results Analysis | 問卷結果分析", "Competitor Analysis | 競爭者分析", "Marketing promotion | 行銷推廣", "Branding & image | 品牌與圖片", "Campaign Performance Analysis | 行銷成效分析", "Customer Service | 顧客服務"],
    key="selected_module",
)

st.button(
    "Refresh results / Reset fields | 重設欄位與結果",
    key="reset_current_module",
    on_click=reset_module_fields,
    args=(selected_module,),
    help="Restore this module's default fields and clear its results. Sidebar settings and other modules are kept. | 將此模組欄位恢復預設並清除結果；保留側欄設定及其他模組。",
)

if selected_module == "Marketing promotion | 行銷推廣":
    marketing_workflow = st.selectbox(
        "Promotion workflow | 推廣工作流程", [COPY_WORKFLOW, PLAN_WORKFLOW], key="marketing_workflow"
    )
    if marketing_workflow == PLAN_WORKFLOW:
        render_marketing_plan(ai_provider, ai_api_key, notion_api_key, notion_parent_page_id, parse_notion_id)
    else:
        st.header("Promotion Inputs | 推廣資訊")

        product_name = st.text_input(
            "Product Name | 產品名稱",
            placeholder="e.g. Matcha Latte | 例：抹茶拿鐵",
            key="copy_product_name",
        )

        product_description = st.text_area(
            "Product Description | 產品描述",
            placeholder=(
                "e.g. A smooth Japanese-style matcha latte made with fresh milk. | "
                "例：一款用新鮮牛奶製作的日式抹茶拿鐵。"
            ),
            key="copy_product_description",
        )

        promotion_type = st.selectbox(
            "Promotion Type | 推廣類型",
            [
                "Buy One Get One Free | 買一送一",
                "Discount | 折扣",
                "Limited-Time Offer | 限時優惠",
                "Free Gift | 贈品",
                "Student Special | 學生優惠",
                "New Product Launch | 新品發布",
            ],
            key="copy_promotion_type",
        )

        target_audience = st.text_input(
            "Target Audience | 目標受眾",
            placeholder="e.g. College students | 例：大學生",
            key="copy_target_audience",
        )

        message_tone = st.selectbox(
            "Message Tone | 文案風格",
            [
                "Fun | 有趣",
                "Professional | 專業",
                "Exciting | 興奮",
                "Cute | 可愛",
                "Luxury | 高端",
                "Friendly | 親切",
                "Urgent | 緊迫",
            ],
            key="copy_message_tone",
        )

        time_frame = st.text_input(
            "Time Frame of Promotion | 推廣時間段",
            placeholder="e.g. Monday to Friday this week | 例：本週一至週五",
            key="copy_time_frame",
        )

        if "output" not in st.session_state:
            st.session_state.output = None

        if st.button("Generate Marketing Content | 產生行銷內容", key="btn_generate_copy"):
            if not ai_api_key:
                st.error(f"Please enter your {ai_provider} API key. | 請輸入 {ai_provider} 金鑰。")
            else:
                prompt = build_prompt(
                    product_name,
                    product_description,
                    promotion_type,
                    target_audience,
                    message_tone,
                    time_frame
                )

                with st.spinner(f"{ai_provider} is generating content... | 正在產生內容..."):
                    try:
                        if ai_provider == "OpenAI":
                            st.session_state.output = generate_with_openai(ai_api_key, prompt)
                        elif ai_provider == "Gemini":
                            st.session_state.output = generate_with_gemini(ai_api_key, prompt)
                        elif ai_provider == "Grok":
                            response = OpenAI(api_key=ai_api_key.strip(), base_url="https://api.x.ai/v1").responses.create(
                                model=select_text_model("Grok", ai_api_key.strip()), input=prompt, store=False
                            )
                            st.session_state.output = json.loads(response.output_text.strip().removeprefix("```json").removesuffix("```").strip())
                        elif ai_provider == "Claude":
                            st.session_state.output = generate_with_claude(ai_api_key, prompt)
                        else:
                            st.session_state.output = generate_with_cursor(ai_api_key, prompt)

                        st.session_state.pop("copy_notion_identity",None)
                        st.success("Marketing content generated! | 行銷內容已產生！")

                    except Exception as e:
                        st.error("Something went wrong while generating content. | 產生內容時發生錯誤。")
                        st.code(str(e))

        if st.session_state.output:
            output = st.session_state.output

            st.header("AI Marketing Outputs | AI 行銷內容")

            st.subheader("IG Caption | Instagram 文案")
            st.write(output["ig_caption"])

            st.subheader("TikTok Script | TikTok 腳本")
            st.write(output["tiktok_script"])

            st.subheader("Hashtags | 話題標籤")
            st.write(output["hashtags"])

            st.subheader("Brief Email Content | 郵件內容")
            st.write(output["brief_email_content"])

            st.subheader("Raw JSON")
            st.json(output)

            if st.button("Save Output to Notion | 儲存到 Notion", key="btn_save_copy",type="primary"):
                if not notion_api_key:
                    st.error(
                        "Enter your Notion API key in the sidebar. | "
                        "請在側欄輸入 Notion 金鑰。"
                    )
                elif not notion_parent_page_id and not st.session_state.marketing_copy_database_id:
                    st.error(
                        "Paste a Notion business page link (first save) or enter an existing database ID. | "
                        "首次儲存請貼上 Notion 商家頁面連結，或填入既有資料庫 ID。"
                    )
                else:
                    with st.spinner(
                        "Saving to Notion... | 正在儲存到 Notion（必要時會建立資料庫）..."
                    ):
                        try:
                            db_id, created_db = ensure_marketing_copy_database(
                                notion_api_key,
                                notion_parent_page_id,
                                notion_column_language,
                                st.session_state.marketing_copy_database_id,
                            )
                            st.session_state.marketing_copy_database_id = db_id
                            save_to_notion(
                                notion_api_key,
                                db_id,
                                notion_column_language,
                                ai_provider,
                                product_name,
                                product_description,
                                promotion_type,
                                target_audience,
                                message_tone,
                                time_frame,
                                output,
                            )
                            if created_db:
                                st.success(
                                    "Created marketing database and saved your row! | "
                                    "已建立文案資料庫並儲存內容！"
                                )
                                show_created_database_details(
                                    db_id, notion_column_language, "marketing_copy"
                                )
                            else:
                                st.success("Saved to Notion database! | 已儲存到 Notion 資料庫！")
                                show_notion_database_link(db_id)

                        except Exception as e:
                            st.error("Something went wrong while saving to Notion. | 儲存到 Notion 時發生錯誤。")
                            st.code(str(e))

elif selected_module == "Branding & image | 品牌與圖片":
    st.header("Branding & Image Inputs | 品牌與圖片資訊")

    st.subheader("Business & product | 業態與產品")

    business_type = st.text_input(
        "Business type | 業態類型 *",
        placeholder=(
            "e.g. Bubble tea shop, café, bakery, skincare retail, gym | "
            "例：手搖飲店、咖啡館、烘焙坊、美妝零售、健身房"
        ),
        help="What kind of business is this for? Not limited to cafés. | 請說明商家類型，不限於咖啡館。",
        key="brand_business_type",
    )

    brand_name = st.text_input(
        "Brand / store name | 品牌／店名",
        placeholder="e.g. Green Leaf Tea | 例：青葉茶坊",
        key="brand_name",
    )

    brand_product_name = st.text_input(
        "Product name | 產品名稱 *",
        placeholder="e.g. Brown Sugar Milk Tea | 例：黑糖奶茶",
        key="brand_product_name",
    )

    brand_product_description = st.text_area(
        "Product description | 產品描述 *",
        placeholder=(
            "Taste, ingredients, size, what makes it special. | "
            "例：口感、成分、容量、特色（如少糖、使用鮮奶）。"
        ),
        key="brand_product_description",
    )

    brand_visual_details = st.text_area(
        "Visual details | 視覺重點 *",
        placeholder=(
            "What must appear in the image: cup type, layers, toppings, colors, setting. | "
            "例：透明杯、分層、珍珠、主色、背景道具（不一定要咖啡館）。"
        ),
        help="Required. Describe exactly what the image should show. | 必填。請描述圖片中必須出現的元素。",
        key="brand_visual_details",
    )

    st.subheader("Look & feel | 風格")

    brand_colors = st.text_input(
        "Brand colors | 品牌色",
        placeholder="e.g. sage green, cream, gold | 例：抹茶綠、米白、金色",
        key="brand_colors",
    )

    visual_style = st.selectbox(
        "Visual style | 視覺風格",
        [
            "Minimal | 極簡",
            "Cute / Kawaii | 可愛",
            "Premium | 高級",
            "Playful | 活潑",
            "Photo-realistic | 寫實",
            "Illustration | 插畫",
            "Retro | 復古",
        ],
        key="brand_visual_style",
    )

    scene_vibe = st.text_input(
        "Scene / atmosphere | 場景氛圍",
        placeholder=(
            "e.g. clean studio, street stall, mall kiosk, home desk | "
            "例：白底棚拍、路邊攤、商場櫃位、居家書桌"
        ),
        key="brand_scene_vibe",
    )

    mascot_or_theme = st.text_input(
        "Mascot or theme (optional) | 吉祥物或主題（選填）",
        placeholder="e.g. capybara mascot, seasonal cherry blossom | 例：水豚吉祥物、櫻花季",
        key="brand_mascot",
    )

    st.subheader("Image output | 輸出設定")

    image_purpose = st.selectbox(
        "Image purpose | 圖片用途",
        [
            "Menu / catalog shot | 菜單／型錄用圖",
            "Promo poster | 促銷海報",
            "Menu tile | 菜單小圖",
            "Social ad | 社群廣告",
        ],
        key="brand_image_purpose",
    )

    aspect_ratio_labels = {
        "1:1 — Instagram feed, Facebook | Instagram 動態、Facebook": "1:1",
        "9:16 — TikTok, Instagram Reels & Stories | TikTok、Instagram Reels／限時動態": "9:16",
        "4:5 — Instagram feed (portrait), Facebook | Instagram 直式動態、Facebook": "4:5",
        "16:9 — YouTube, X | YouTube、X（Twitter）": "16:9",
    }
    aspect_ratio_choice = st.selectbox(
        "Aspect ratio | 比例",
        list(aspect_ratio_labels.keys()),
        key="brand_aspect_ratio",
    )
    aspect_ratio = aspect_ratio_labels[aspect_ratio_choice]

    include_text_on_image = st.checkbox(
        "Include text on image | 圖上加入文字",
        key="brand_include_text",
    )

    image_headline = st.text_input(
        "Headline on image | 主標",
        placeholder="e.g. NEW MILK TEA | 例：全新奶茶",
        disabled=not include_text_on_image,
        key="brand_headline",
    )

    image_subhead = st.text_input(
        "Subhead / offer | 副標",
        placeholder="e.g. Buy 1 Get 1 · This week | 例：買一送一 · 本週限定",
        disabled=not include_text_on_image,
        key="brand_subhead",
    )

    overlay_language = st.selectbox(
        "Overlay language | 文字語言",
        ["English", "Traditional Chinese | 繁體中文", "Bilingual | 雙語"],
        disabled=not include_text_on_image,
        key="brand_overlay_language",
    )

    avoid_in_image = st.text_area(
        "Avoid in image | 避免出現",
        placeholder="e.g. competitor logos, misspelled text, cluttered background",
        key="brand_avoid",
    )

    st.caption("* Required for image generation | 產生圖片時必填")

    current_image_prompt = build_branding_image_prompt(
        business_type, brand_name, brand_product_name, brand_product_description,
        brand_visual_details, brand_colors, visual_style, scene_vibe, mascot_or_theme,
        image_purpose, aspect_ratio, include_text_on_image,
        image_headline if include_text_on_image else "",
        image_subhead if include_text_on_image else "",
        overlay_language if include_text_on_image else "", avoid_in_image,
    )
    if ai_provider in IMAGE_MODELS:
        st.caption(f"Image model | 圖片模型：{IMAGE_MODELS[ai_provider]}")
        if ai_provider == "OpenAI" and aspect_ratio != "1:1":
            st.caption("The image is cropped to your selected ratio. | 圖片將裁切為所選比例。")
    else:
        st.info("Choose OpenAI or Gemini in the sidebar to generate images. | 請在側欄選擇 OpenAI 或 Gemini 產生圖片。")

    if st.button("Generate branding image | 產生品牌圖片", key="btn_generate_brand", disabled=ai_provider not in IMAGE_MODELS):
        missing = []
        if not business_type.strip():
            missing.append("Business type | 業態類型")
        if not brand_product_name.strip():
            missing.append("Product name | 產品名稱")
        if not brand_product_description.strip():
            missing.append("Product description | 產品描述")
        if not brand_visual_details.strip():
            missing.append("Visual details | 視覺重點")
        if not ai_api_key:
            st.error(f"Please enter your {ai_provider} API key. | 請輸入 {ai_provider} 金鑰。")
        elif missing:
            st.error(
                "Please fill required fields: "
                + ", ".join(missing)
                + " | 請填寫必填欄位："
                + "、".join(missing)
            )
        else:
            with st.spinner("Generating image... | 正在產生圖片..."):
                try:
                    data = generate_branding_image(ai_provider, ai_api_key, current_image_prompt, aspect_ratio)
                    st.session_state.brand_generated_image = {
                        "data": data, "prompt": current_image_prompt,
                        "provider": ai_provider, "model": IMAGE_MODELS[ai_provider],
                    }
                    st.session_state.pop("brand_notion_identity",None)
                    st.success("Image generated! | 圖片已產生！")
                except Exception as e:
                    st.error("Image generation failed. Check your API key, model access, and billing, then retry. | 圖片產生失敗，請檢查金鑰、模型權限與帳務後重試。")
                    st.caption(str(e))

    generated_image = st.session_state.get("brand_generated_image")
    matching_image = generated_image if generated_image and generated_image["prompt"] == current_image_prompt else None
    if generated_image:
        st.image(generated_image["data"], caption=generated_image["model"])
        st.download_button("Download image | 下載圖片", generated_image["data"],
                           file_name="branding.png", mime="image/png")
        if not matching_image:
            st.info("Your inputs have changed. Generate a new image before saving it with this brief. | 輸入已變更，請重新產生圖片後再與此品牌資訊一起儲存。")

    if st.button("Save to Notion | 儲存到 Notion", key="btn_save_brand",type="primary"):
        missing = []
        if not business_type.strip():
            missing.append("Business type | 業態類型")
        if not brand_product_name.strip():
            missing.append("Product name | 產品名稱")
        if not brand_product_description.strip():
            missing.append("Product description | 產品描述")
        if not brand_visual_details.strip():
            missing.append("Visual details | 視覺重點")
        if not notion_api_key:
            st.error(
                "Enter your Notion API key in the sidebar. | "
                "請在側欄輸入 Notion 金鑰。"
            )
        elif missing:
            st.error(
                "Please fill required fields: "
                + ", ".join(missing)
                + " | 請填寫必填欄位："
                + "、".join(missing)
            )
        elif not notion_parent_page_id and not st.session_state.branding_images_database_id:
            st.error(
                "Paste a Notion business page link (first save) or enter an existing database ID. | "
                "首次儲存請貼上 Notion 商家頁面連結，或填入既有資料庫 ID。"
            )
        else:
            overlay = overlay_language if include_text_on_image else ""
            headline = image_headline if include_text_on_image else ""
            subhead = image_subhead if include_text_on_image else ""
            prompt = build_branding_image_prompt(
                business_type,
                brand_name,
                brand_product_name,
                brand_product_description,
                brand_visual_details,
                brand_colors,
                visual_style,
                scene_vibe,
                mascot_or_theme,
                image_purpose,
                aspect_ratio,
                include_text_on_image,
                headline,
                subhead,
                overlay,
                avoid_in_image,
            )
            with st.spinner(
                "Saving to Notion... | 正在儲存到 Notion（必要時會建立資料庫）..."
            ):
                try:
                    db_id, created_db = ensure_branding_images_database(
                        notion_api_key,
                        notion_parent_page_id,
                        notion_column_language,
                        st.session_state.branding_images_database_id,
                    )
                    st.session_state.branding_images_database_id = db_id
                    save_branding_to_notion(
                        notion_api_key,
                        db_id,
                        notion_column_language,
                        matching_image["model"] if matching_image else ai_provider,
                        brand_product_name,
                        business_type,
                        brand_name,
                        brand_product_description,
                        brand_visual_details,
                        brand_colors,
                        visual_style,
                        scene_vibe,
                        mascot_or_theme,
                        image_purpose,
                        aspect_ratio,
                        headline,
                        subhead,
                        overlay,
                        avoid_in_image,
                        prompt,
                        image_data=matching_image["data"] if matching_image else None,
                    )
                    if matching_image:
                        st.success("Image attached in Notion! | 圖片已儲存到 Notion！")
                    else:
                        st.caption("Brief saved without an image. | 已儲存品牌資訊，未附圖片。")
                    if created_db:
                        st.success(
                            "Created images database and saved your brief! | "
                            "已建立圖片資料庫並儲存品牌資訊！"
                        )
                        show_created_database_details(
                            db_id, notion_column_language, "branding_images"
                        )
                    else:
                        st.success(
                            "Saved branding brief to Notion! | 已儲存品牌資訊到 Notion！"
                        )
                        show_notion_database_link(db_id)
                except Exception as e:
                    st.error("Something went wrong while saving to Notion. | 儲存到 Notion 時發生錯誤。")
                    st.code(str(e))

elif selected_module == "Customer Service | 顧客服務":
    st.header("Customer Service | 顧客服務")
    st.caption("Answers use your loaded business reference. Review and confirm before any ticket is saved. | 回覆依據已載入的商家資料；工單須確認後才儲存。")
    service_provider = ai_provider
    service_key = ai_api_key.strip()
    service_model = DEFAULT_MODELS[service_provider]
    st.caption(f"Using {service_provider} from the sidebar. | 使用側欄設定的 {service_provider}。")
    if service_provider == "Cursor":
        st.caption("Uses Cursor Cloud Agents; replies may take longer. | 使用 Cursor 雲端代理，回覆可能較慢。")
    knowledge = st.session_state.get("support_knowledge")
    if not knowledge:
        if st.session_state.get("service_knowledge_error"):
            st.error("The page may be connected, but its business reference could not be loaded. Chat needs readable text directly on the knowledge page. | 頁面可能已連線，但無法載入商家參考資料。聊天需要知識頁面上的可讀文字。")
            details = st.session_state.get("service_knowledge_details")
            if details:
                with st.expander("Knowledge loading error | 知識載入錯誤", expanded=True):
                    st.caption("Copy the report using its top-right copy icon. | 使用報告右上角圖示複製錯誤。")
                    st.code(json.dumps(details, ensure_ascii=False, indent=2), language=None, wrap_lines=True)
            if st.button("Retry loading business reference | 重新載入商家資料", key="retry_service_knowledge"):
                st.session_state.service_knowledge_error = False
                st.rerun()
        elif separate_knowledge and not knowledge_link.strip():
            st.warning("Enter the separate knowledge page link under Advanced, or turn off that option to use your business page. | 請在進階設定填入另一個知識頁面連結，或取消此選項以使用商家頁面。")
        else:
            st.info("Enter your Notion key and business page link in the sidebar to load the reference automatically. | 在側欄填入 Notion 金鑰與商家頁面連結，即可自動載入參考資料。")
    elif not service_key:
        st.info("Business reference is ready. Enter your AI API key in the sidebar to start chatting. | 商家資料已就緒，請在側欄輸入 AI 金鑰以開始對話。")
    if knowledge:
        st.success("Knowledge loaded | 已載入知識：" + knowledge["title"])
        st.link_button("Open business reference | 開啟商家資料", knowledge["url"])
        with st.expander("Loaded reference | 已載入的參考資料"):
            st.text(knowledge["text"])
    if st.button("New conversation | 新對話"):
        for state_key in list(st.session_state):
            if state_key.startswith("support_") and state_key != "support_knowledge":
                del st.session_state[state_key]
        st.session_state.support_messages = []
        st.rerun()
    for message in st.session_state.support_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    message = st.chat_input("Ask about this business | 詢問商家資訊", disabled=not knowledge or not service_key.strip(), key="support_chat_input")
    if message:
        if len(message) > 4000 or sum(len(m["content"]) for m in st.session_state.support_messages) + len(message) > 40000:
            st.warning("Conversation is too long. Shorten your message or start a new conversation. | 對話過長，請縮短訊息或開始新對話。")
        else:
            history = st.session_state.support_messages + [{"role": "user", "content": message}]
            try:
                with st.spinner(f"{service_provider} is replying... | {service_provider} 回覆中..."):
                    answer = service_reply(service_provider, service_key, service_model.strip(), knowledge, history)
                st.session_state.support_messages = history + [{"role": "assistant", "content": answer}]
                st.rerun()
            except Exception as error:
                st.error(service_connection_error(error))
                with st.expander("Reply error details | 回覆錯誤詳細資訊", expanded=True):
                    show_copyable_error(error, service_provider, service_model, service_key)
    if st.button("Create support ticket | 建立客服工單", disabled=not knowledge or not service_key.strip() or not st.session_state.support_messages):
        try:
            with st.spinner("Preparing ticket draft... | 正在準備工單草稿..."):
                draft = service_reply(service_provider, service_key, service_model.strip(), knowledge, st.session_state.support_messages, draft=True)
            for field, value in draft.items():
                st.session_state["support_field_" + field] = value
            st.session_state.support_draft = draft
            st.session_state.support_ticket_history = list(st.session_state.support_messages)
            st.session_state.support_reference = new_reference()
            st.session_state.pop("support_saved", None)
        except Exception as error:
            st.error(service_connection_error(error))
            with st.expander("Ticket draft error details | 工單草稿錯誤詳細資訊", expanded=True):
                show_copyable_error(error, service_provider, service_model, service_key)
    if st.session_state.get("support_draft") and not st.session_state.get("support_saved"):
        st.subheader("Review ticket | 檢查工單")
        st.caption("Only explicitly confirmed tickets are saved. Staff notifications are not configured. | 僅儲存確認的工單；尚未設定通知人員。")
        with st.form("support_review"):
            subject = st.text_input("Subject | 主旨", key="support_field_subject", max_chars=200)
            name = st.text_input("Name (optional) | 姓名（選填）", key="support_field_name", max_chars=200)
            contact = st.text_input("Contact (optional) | 聯絡方式（選填）", key="support_field_contact", max_chars=500)
            category = st.text_input("Category | 類別", key="support_field_category", max_chars=200)
            summary = st.text_area("Issue summary | 問題摘要", key="support_field_summary", max_chars=5000)
            include_history = st.checkbox("Include conversation in ticket | 工單附上對話紀錄", key="support_include_history")
            confirmed = st.form_submit_button("Confirm and create support ticket | 確認並建立客服工單",type="primary")
        if confirmed:
            if not subject.strip() or not summary.strip() or not notion_api_key.strip() or not notion_parent_page_id.strip():
                st.error("Subject, summary, Notion key and business page link are required. | 請填寫主旨、摘要、Notion 金鑰與商家頁面連結。")
            else:
                try:
                    with st.spinner("Saving ticket... | 正在儲存工單..."):
                        result = save_ticket(notion_api_key, parse_notion_id(notion_parent_page_id), notion_column_language,
                            {"subject": subject, "name": name, "contact": contact, "category": category, "summary": summary},
                            st.session_state.support_ticket_history, include_history, st.session_state.support_reference,
                            prepare_notion_data_source)
                    st.session_state.support_saved = result.get("url") or "https://www.notion.so/" + result["id"].replace("-", "")
                    st.rerun()
                except Exception:
                    st.error("Ticket save could not be confirmed. Check Notion access and retry; the same ticket reference will be reused. | 無法確認工單儲存結果，請檢查 Notion 權限後重試，將沿用相同工單編號。")
    if st.session_state.get("support_saved"):
        st.success("Support ticket saved | 客服工單已儲存：" + st.session_state.support_reference)
        st.link_button("Open ticket in Notion | 在 Notion 開啟工單", st.session_state.support_saved)


elif selected_module == "Survey Results Analysis | 問卷結果分析":
    render_survey_analysis(ai_provider, ai_api_key)
elif selected_module == "Campaign Performance Analysis | 行銷成效分析":
    render_campaign_analysis(ai_provider, ai_api_key, notion_api_key, notion_parent_page_id, parse_notion_id)
elif selected_module == "Competitor Analysis | 競爭者分析":
    render_competitor_analysis(ai_provider, ai_api_key, notion_api_key, notion_parent_page_id, parse_notion_id)
