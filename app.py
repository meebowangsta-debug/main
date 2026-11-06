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


IMAGE_MODELS = {"OpenAI": "gpt-image-1.5", "Gemini": "gemini-2.5-flash-image"}


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


def test_openai_connection(api_key):
    client = OpenAI(api_key=api_key)
    client.models.list()


def test_gemini_connection(api_key):
    client = genai.Client(api_key=api_key)
    client.models.get(model="gemini-2.5-flash")


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
        model="gpt-5.2",
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
        model="gemini-2.5-flash",
        contents=prompt
    )

    text = response.text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def generate_with_claude(api_key, prompt):
    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def generate_with_cursor(api_key, prompt):
    auth = (api_key.strip(), "")
    max_wait_seconds = 300
    poll_interval_seconds = 2

    with httpx.Client(timeout=60.0) as client:
        create_response = client.post(
            f"{CURSOR_API_BASE}/v1/agents",
            auth=auth,
            json={
                "prompt": {"text": prompt},
                "model": {"id": "composer-2.5"},
            },
        )
        create_response.raise_for_status()
        created = create_response.json()
        agent_id = created["agent"]["id"]
        run_id = created["run"]["id"]

        deadline = time.time() + max_wait_seconds
        run_data = None
        while time.time() < deadline:
            run_response = client.get(
                f"{CURSOR_API_BASE}/v1/agents/{agent_id}/runs/{run_id}",
                auth=auth,
            )
            run_response.raise_for_status()
            run_data = run_response.json()
            status = run_data["status"]
            if status in ("FINISHED", "ERROR", "CANCELLED", "EXPIRED"):
                break
            time.sleep(poll_interval_seconds)
        else:
            raise TimeoutError("Cursor agent run timed out")

        if run_data["status"] != "FINISHED":
            raise RuntimeError(f"Cursor run ended with status {run_data['status']}")

        text = (run_data.get("result") or "").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)


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
            "需要 Notion 金鑰與父頁面連結。"
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
            "需要 Notion 金鑰與父頁面連結。"
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
    image_files = upload_notion_image(notion, notion_api_key, image_data) if image_data else []
    notion.pages.create(
        parent={"type": "data_source_id", "data_source_id": source_id},
        properties={
            cols["product_name"]: {
                "title": [{"text": {"content": brand_product_name or ""}}]
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
    notion.pages.create(
        parent={"type": "data_source_id", "data_source_id": source_id},
        properties={
            cols["product_name"]: {
                "title": [{"text": {"content": product_name or ""}}]
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
    [data-testid="stSidebar"] :is(.st-key-ai_provider, .st-key-ai_api_key,
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
        ["OpenAI", "Gemini", "Claude", "Cursor"],
        key="ai_provider",
    )

    ai_api_key = st.text_input(
        f"{ai_provider} API Key | {ai_provider} 金鑰",
        type="password",
        key="ai_api_key",
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
                    if ai_provider == "OpenAI":
                        test_openai_connection(ai_api_key)
                    elif ai_provider == "Gemini":
                        test_gemini_connection(ai_api_key)
                    elif ai_provider == "Claude":
                        test_claude_connection(ai_api_key)
                    else:
                        test_cursor_connection(ai_api_key)
                    st.success(f"{ai_provider} connection successful! | 連線成功！")
                except Exception as e:
                    st.error(f"Connection failed | 連線失敗：{e}")

    st.header("Notion Settings | Notion 設定")

    st.caption(
        "Share one empty Notion page with your integration. "
        "Databases are created automatically the first time you save. | "
        "將一個空白頁分享給整合；首次按「儲存到 Notion」時會自動建立資料庫。"
    )

    notion_api_key = st.text_input(
        "Notion API Key | Notion 金鑰",
        type="password",
        key="notion_api_key",
    )

    notion_parent_page_id = st.text_input(
        "Parent Notion page link | Notion 父頁面連結",
        placeholder="https://www.notion.so/My-page-0123456789abcdef0123456789abcdef",
        help=(
            "Paste the link to the Notion page where your databases should be created. "
            "In Notion, open the page and choose Copy link. Share the page with your "
            "integration. A page ID also works. | 貼上要建立資料庫的 Notion 頁面連結。"
            "在 Notion 開啟頁面並選擇複製連結，並將頁面分享給整合。也可填入頁面 ID。"
        ),
        key="notion_parent_page_id",
    )

    if st.button("Test Notion page connection | 測試 Notion 頁面連線", key="btn_test_parent_page"):
        if not notion_api_key.strip() or not notion_parent_page_id.strip():
            st.warning(
                "Enter your Notion API key and paste the parent page link first. | "
                "請先輸入 Notion 金鑰並貼上父頁面連結。"
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


tab_copy, tab_branding = st.tabs(
    ["Marketing promotion | 行銷推廣", "Branding & image | 品牌與圖片"]
)

with tab_copy:
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
                    elif ai_provider == "Claude":
                        st.session_state.output = generate_with_claude(ai_api_key, prompt)
                    else:
                        st.session_state.output = generate_with_cursor(ai_api_key, prompt)

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

        if st.button("Save Output to Notion | 儲存到 Notion", key="btn_save_copy"):
            if not notion_api_key:
                st.error(
                    "Enter your Notion API key in the sidebar. | "
                    "請在側欄輸入 Notion 金鑰。"
                )
            elif not notion_parent_page_id and not st.session_state.marketing_copy_database_id:
                st.error(
                    "Paste a parent Notion page link (first save) or enter an existing database ID. | "
                    "首次儲存請貼上 Notion 父頁面連結，或填入既有資料庫 ID。"
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

with tab_branding:
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

    if st.button("Save to Notion | 儲存到 Notion", key="btn_save_brand"):
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
                "Paste a parent Notion page link (first save) or enter an existing database ID. | "
                "首次儲存請貼上 Notion 父頁面連結，或填入既有資料庫 ID。"
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
