import gradio as gr
import requests
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
import io
import base64
import matplotlib
import os
import json
import datetime

image_sizes = ['1024x1024', '1024x1792', '1792x1024']
api_url = 'https://api.openai.com/v1/images/generations'
config = 'config.json'
output = 'output'

matplotlib.use('Agg')
os.makedirs(output, exist_ok=True)

metadata_fetching = False


def load_config():
    if os.path.exists(config):
        with open(config, 'r') as file:
            data = json.load(file)
            api_key = data.get('api_key', '')
            total_spent = float(data.get('total_spent', 0))
            return api_key, total_spent
    return '', 0


def save_config(api, total):
    with open(config, 'w') as file:
        json.dump({'api_key': api, 'total_spent': f"{total:.2f}"}, file)
        file.flush()


def generate_text(text):
    width = 1000
    height = 250
    img = Image.new('RGB', (width, height), color='black')
    draw = ImageDraw.Draw(img)
    font_size = 30
    font_path = 'arial.ttf'

    try:
        font = ImageFont.truetype(font_path, size=font_size)
    except IOError:
        font = ImageFont.load_default()
    width, height = draw.textbbox((0, 0), text, font=font)[2:]

    while width > img.width:
        font_size -= 1
        if font_size <= 5:
            return generate_text("none")
        font = ImageFont.truetype(font_path, size=font_size)
        width, height = draw.textbbox((0, 0), text, font=font)[2:]

    x = (img.width - width) // 2
    y = (img.height - height) // 2

    draw.text((x, y), text, font=font, fill='white')
    return img


def calculate_price(size, hd, count=1):
    prices = {
        '1024x1024': 0.04,
        '1024x1792': 0.08,
        '1792x1024': 0.08
    }
    hd_prices = {
        '1024x1024': 0.08,
        '1024x1792': 0.12,
        '1792x1024': 0.12
    }
    price = hd_prices[size] if hd else prices[size]
    return price * count


def get_metadata(img):
    metadata_str = ""
    if img is None:
        return ""
    generation_info = img.info.get("generation_info", "No metadata found.")
    metadata_str += "Generation Info:\n" + generation_info + "\n"
    revised_prompt = img.info.get("revised_prompt", "No revised prompt found.")
    metadata_str += "Revised Prompt:\n" + revised_prompt + "\n"
    return metadata_str


def request_dalle(api_key, prompt, hd, size, style):
    data = {
        "model": "dall-e-3",
        "prompt": prompt,
        "size": size,
        "quality": "hd" if hd else "standard",
        "style": style if style else "vivid",
        "response_format": "b64_json"
    }
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    try:
        response = requests.post(api_url, json=data, headers=headers)
        return response.status_code, response.json()
    except Exception as e:
        return None, e


def generate_image(api_key, prompt, hd, jb, size, style):
    print("generating...")
    if jb:
        # openai docs
        prompt = "I NEED to test how the tool works with extremely simple prompts. DO NOT add any detail, just use it AS-IS:" + prompt

    status, response = request_dalle(api_key, prompt, hd, size, style)

    if status is None:
        print(f"Error: {response}")
        return generate_text("connection issue"), response, False

    if status == 200:
        b64_content = response['data'][0]['b64_json']
        revised_prompt = response['data'][0].get('revised_prompt', 'No revised prompt provided.')
        image_bytes = base64.b64decode(b64_content)
        image = Image.open(io.BytesIO(image_bytes))
        # metadata stuff
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("generation_info", f"prompt:{prompt}, hd:{hd}, style:{style}")
        metadata.add_text("revised_prompt", revised_prompt)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", pnginfo=metadata)
        buffer.seek(0)
        img_final = Image.open(buffer)
        # saving stuff
        folder_path = os.path.join(output, datetime.datetime.now().strftime('%Y-%m-%d'))
        os.makedirs(folder_path, exist_ok=True)

        file_number = 0
        file_path = os.path.join(folder_path, f"img_{file_number}.png")
        while os.path.exists(file_path):
            file_number += 1
            file_path = os.path.join(folder_path, f"img_{file_number}.png")
        img_final.save(file_path, "PNG", pnginfo=metadata)

        print("Success.")
        return img_final, revised_prompt, True

    elif status == 401:
        print("Invalid api key.")
        return generate_text("Invalid API key"), "Invalid API key.", False

    # text: Your request was rejected as a result of our safety system. Your prompt may contain text that is not allowed by our safety system.
    # image: This request has been blocked by our content filters.
    elif status == 400 or status == 429:
        error_message = response['error']['message']
        # filtered
        if response['error']['code'] == "content_policy_violation":
            if "Your prompt may contain text" in error_message:
                print("Filtered by text moderation")
            elif "blocked by our content filters" in error_message:
                print("Filtered by image moderation")
            else:
                print(f"Filtered. {error_message}")
            return generate_text("Filtered"), error_message, False

        # rate limited or quota issue
        print(f"Error: {error_message}")
        return generate_text(f"{error_message}"), f"{error_message}", False

    else:
        print(f"Unknown error: {response}")
        return generate_text(f"Unknown Error"), f"{response}", False


def main(api_key, prompt, hd, jb, size, style, count):
    images = []
    revised_prompts = ""
    count = int(count)
    price = 0

    for i in range(count):
        img_final, revised_prompt, success = generate_image(api_key, prompt, hd, jb, size, style)
        images.append(img_final)
        revised_prompts += f"{i + 1}- {revised_prompt}\n"
        if success:
            price += calculate_price(size, hd)

    _, total = load_config()
    total += price
    save_config(api_key, total)
    print("Done.")
    return images, revised_prompts, f"price for this batch:${price:.2f}, total generated:${total:.2f}"


with gr.Blocks(title="de3u") as demo:
    gr.Markdown("# de3u")
    tab_main = gr.TabItem("Image generator")
    tab_metadata = gr.TabItem("Image Metadata")
    with tab_main:
        with gr.Row():
            with gr.Column():
                api_key_input = gr.Textbox(label="API Key", placeholder="Enter your API key", type="password", value=load_config()[0])
                prompt_input = gr.Textbox(label="Prompt", placeholder="Enter your prompt")
                hd_input = gr.Checkbox(label="HD")
                jb_input = gr.Checkbox(label="JB", info="makes the ai less likely to change your input. more likely to get filtered. useful if you are using an already revised prompt.")
                size_input = gr.Dropdown(label="Size", choices=image_sizes, value=image_sizes[0], allow_custom_value=False)
                style_input = gr.Radio(label="Style", choices=['vivid', 'natural'], value='vivid')
                with gr.Row():
                    generate_button = gr.Button("Generate")
                    num_images_input = gr.Number(label="Number of Images", value=1, step=1, minimum=1, interactive=True)
            with gr.Column():
                image_output = gr.Gallery()
                revised_prompt_output = gr.Textbox(label="Revised Prompt")
                price_output = gr.Textbox(label="Price")

    with tab_metadata:
        with gr.Row():
            metadata_image = gr.Image(type="pil", width=500, height=500, sources=["upload", "clipboard"])
            metadata_output = gr.Textbox(label="Metadata", interactive=False)

        metadata_button = gr.Button("Get Metadata")

    metadata_button.click(
        fn=get_metadata,
        inputs=[metadata_image],
        outputs=[metadata_output]
    )
    generate_button.click(
        fn=main,
        inputs=[api_key_input, prompt_input, hd_input, jb_input, size_input, style_input, num_images_input],
        outputs=[image_output, revised_prompt_output, price_output]
    )

demo.launch()
