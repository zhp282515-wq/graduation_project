from rich import print as rprint

import requests
import os
from dotenv import load_dotenv

load_dotenv(override=True)

token = os.getenv("MINERU_API_KEY")
base_url = "https://mineru.net/api/v4/extract/task"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

# 1. 请求上传地址
file_path = "D:\\1oveb\\毕业设计\\Graduation-Project\\data\\附件3：江西省普通本科高校教改课题申报书（附申报活页）.docx"
file_name = os.path.basename(file_path)

batch_data = {
    "files": [
        {"name": file_name, "data_id": "optics-doc"}
    ],
    "model_version": "vlm"
}

res = requests.post(
    f"{base_url}/file-urls/batch",
    headers=header,
    json=batch_data
)
result = res.json()
print("请求上传地址:", result)

if result.get("code") != 0:
    raise Exception(f"获取上传地址失败: {result['msg']}")

batch_id = result["data"]["batch_id"]
upload_url = result["data"]["file_urls"][0]

# 2. PUT 上传文件（注意：不要加 Content-Type 头）
with open(file_path, "rb") as f:
    put_res = requests.put(upload_url, data=f)

print("上传状态码:", put_res.status_code)
if put_res.status_code != 200:
    raise Exception(f"上传失败: {put_res.status_code}")

# 3. 轮询获取结果
import time

task_result = None
while True:
    check_res = requests.get(
        f"{base_url}/extract-results/batch/{batch_id}",
        headers=header
    )
    check_result = check_res.json()
    task_state = check_result["data"]["extract_result"][0]["state"]

    if task_state == "done":
        task_result = check_result["data"]["extract_result"][0]
        break
    elif task_state == "failed":
        raise Exception(f"解析失败: {task_result['err_msg']}")

    print(f"当前状态: {task_state}，等待中...")
    time.sleep(5)

print("解析完成！")
print("结果下载地址:", task_result["full_zip_url"])