from utils.path_tool import get_abs_path

def get_prompt() -> str:

    prompt_path = get_abs_path("prompts/system_prompt.md")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read().strip()
    return prompt

if __name__ == '__main__':
    print(get_prompt())