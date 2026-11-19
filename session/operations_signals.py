"""Campus topics and safe keyword extraction for aggregate reporting."""
import re
import unicodedata

TOPICS = {
    "教务": ("选课", "退课", "考试", "补考", "成绩", "教务", "学籍", "转专业", "课表", "学分", "校历", "毕业"),
    "学工": ("奖学金", "学生证", "入党", "入团", "社团", "请假", "学生工作", "军训", "迎新", "志愿服务"),
    "生活": ("食堂", "宿舍", "快递", "天气", "校园网", "班车", "校医院", "报修", "操场", "一卡通"),
    "财务": ("学费", "缴费", "退费", "报销", "助学金", "助学贷款", "收费", "发票"),
    "学习": ("图书馆", "借书", "还书", "自习", "考研", "四六级", "科研", "实验室", "论文", "课程"),
    "闲聊": ("你好", "早上好", "晚上好", "谢谢", "晚安", "笑话", "你是谁"),
}
_KEYWORDS = tuple(word for words in TOPICS.values() for word in words) + (
    "开放时间", "联系方式", "办理流程", "申请材料", "报名时间", "预约", "寒假", "暑假", "查重",
)


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"1[3-9]\d(?:[\s-]?\d){8}|\d(?:[\s-]?\d){16}[\s-]?[\dx]|\d(?:[\s.-]?\d){5,}", " ", text)
    return " ".join(re.findall(r"[\w]+", text.replace("_", " ")))


def keywords(text):
    safe = normalize(text)
    return [word for word in _KEYWORDS if word in safe][:6]


def topic(text):
    counts = {name: sum(word in text for word in words) for name, words in TOPICS.items()}
    label = max(counts, key=counts.get)
    return label if counts[label] else "其他"


def similar(first, second):
    def grams(text):
        clean = "".join(re.findall(r"[^\W_]", unicodedata.normalize("NFKC", text[:2000]).casefold()))
        return {clean[i:i+2] for i in range(len(clean)-1)} if len(clean) >= 4 else set()

    left, right = grams(first), grams(second)
    return bool(left and right and len(left & right) / len(left | right) >= 0.8)
