"""
Setup Rich Menu for HUI ATELIER LINE Bot
Uses LINE Messaging API to create a rich menu with 6 areas
"""

import requests
import json
import sys

CHANNEL_ACCESS_TOKEN = "noDsf9UAdPCgOEJwFdYEUevKnxtuhO+gKbZxA8TPVG2JVpRC2HvG7lGUGe5ESW+IG2HmB7fo4BrNaSDIohiVpGCGkrF5cq/M2r1GDz+9iajwm0x5iJfIZXXUjo2dXCiuo6MD6TFu+fWa+JhlUqWyCgdB04t89/1O/w1cDnyilFU="

HEADERS = {
    "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

# Rich Menu layout: 2 rows x 3 columns
# Image size: 2500 x 1686 (standard LINE rich menu size)
# Top row: 藝術收藏, 沉浸式體驗, 藝術調香
# Bottom row: 企業合作, 品牌孵化, 關於我們

RICH_MENU_BODY = {
    "size": {
        "width": 2500,
        "height": 1686
    },
    "selected": True,
    "name": "HUI ATELIER 服務選單",
    "chatBarText": "點我開啟選單",
    "areas": [
        {
            "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "藝術收藏"}
        },
        {
            "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
            "action": {"type": "message", "text": "沉浸式體驗"}
        },
        {
            "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
            "action": {"type": "message", "text": "藝術調香"}
        },
        {
            "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
            "action": {"type": "message", "text": "企業合作"}
        },
        {
            "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
            "action": {"type": "message", "text": "品牌孵化"}
        },
        {
            "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
            "action": {"type": "message", "text": "關於我們"}
        }
    ]
}


def create_rich_menu():
    """Step 1: Create rich menu object"""
    print("Step 1: Creating rich menu...")
    url = "https://api.line.me/v2/bot/richmenu"
    resp = requests.post(url, headers=HEADERS, json=RICH_MENU_BODY)
    print(f"  Status: {resp.status_code}")
    print(f"  Response: {resp.text}")
    if resp.status_code != 200:
        print("ERROR: Failed to create rich menu")
        sys.exit(1)
    rich_menu_id = resp.json()["richMenuId"]
    print(f"  Rich Menu ID: {rich_menu_id}")
    return rich_menu_id


def upload_image(rich_menu_id, image_path):
    """Step 2: Upload rich menu image"""
    print(f"\nStep 2: Uploading image to rich menu {rich_menu_id}...")
    url = f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "image/jpeg"
    }
    with open(image_path, "rb") as f:
        resp = requests.post(url, headers=headers, data=f)
    print(f"  Status: {resp.status_code}")
    print(f"  Response: {resp.text}")
    if resp.status_code != 200:
        print("ERROR: Failed to upload image")
        sys.exit(1)
    print("  Image uploaded successfully!")


def set_default(rich_menu_id):
    """Step 3: Set as default rich menu"""
    print(f"\nStep 3: Setting rich menu {rich_menu_id} as default...")
    url = f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}"
    resp = requests.post(url, headers={"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"})
    print(f"  Status: {resp.status_code}")
    print(f"  Response: {resp.text}")
    if resp.status_code != 200:
        print("ERROR: Failed to set default rich menu")
        sys.exit(1)
    print("  Rich menu set as default!")


def delete_existing_menus():
    """Delete all existing rich menus first"""
    print("Step 0: Checking existing rich menus...")
    url = "https://api.line.me/v2/bot/richmenu/list"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        menus = resp.json().get("richmenus", [])
        if menus:
            print(f"  Found {len(menus)} existing rich menu(s), deleting...")
            for menu in menus:
                del_url = f"https://api.line.me/v2/bot/richmenu/{menu['richMenuId']}"
                del_resp = requests.delete(del_url, headers=HEADERS)
                print(f"  Deleted {menu['richMenuId']}: {del_resp.status_code}")
        else:
            print("  No existing rich menus found.")
    else:
        print(f"  Warning: Could not list rich menus: {resp.status_code}")


if __name__ == "__main__":
    image_path = "/home/ubuntu/upload/AA77CEAF-9504-49CB-A921-0C40B541207B.png"
    
    # Check image dimensions - LINE requires 2500x1686 or 2500x843
    from PIL import Image
    img = Image.open(image_path)
    print(f"Original image size: {img.size}")
    
    # Resize to 2500x1686 and compress as JPEG (LINE limit: 1MB)
    target_size = (2500, 1686)
    print(f"Resizing image from {img.size} to {target_size}...")
    img_resized = img.resize(target_size, Image.LANCZOS)
    # Convert to RGB (JPEG doesn't support alpha)
    if img_resized.mode == 'RGBA':
        img_resized = img_resized.convert('RGB')
    resized_path = "/home/ubuntu/christy-line-bot/richmenu_image.jpg"
    img_resized.save(resized_path, "JPEG", quality=80)
    image_path = resized_path
    import os as _os
    file_size = _os.path.getsize(resized_path)
    print(f"  Saved resized image to {resized_path} ({file_size/1024:.0f} KB)")
    
    # Execute steps
    delete_existing_menus()
    rich_menu_id = create_rich_menu()
    upload_image(rich_menu_id, image_path)
    set_default(rich_menu_id)
    
    print(f"\n✅ Rich Menu setup complete!")
    print(f"   Rich Menu ID: {rich_menu_id}")
    print(f"   Status: Active (default for all users)")
