"""轻量级标签提取器 — 基于规则匹配从标题和摘要中提取 3-5 个标签。"""

import re

# ── 关键词 → 标签映射（优先匹配长词） ──
_KEYWORD_TAGS = [
    # 编程语言
    ("python", "Python"), ("java", "Java"), ("javascript", "JavaScript"),
    ("typescript", "TypeScript"), ("go ", "Go"), ("golang", "Go"),
    ("rust", "Rust"), ("c++", "C++"), ("c语言", "C"), ("php", "PHP"),
    ("swift", "Swift"), ("kotlin", "Kotlin"), ("ruby", "Ruby"),
    ("scala", "Scala"), ("r语言", "R"), ("matlab", "MATLAB"),

    # AI / ML
    ("机器学习", "机器学习"), ("深度学习", "深度学习"),
    ("人工智能", "人工智能"), ("神经网络", "神经网络"),
    ("大模型", "大模型"), ("llm", "LLM"), ("大语言模型", "LLM"),
    ("chatgpt", "ChatGPT"), ("gpt", "GPT"), ("openai", "OpenAI"),
    ("transformer", "Transformer"), ("bert", "BERT"),
    ("diffusion", "Diffusion"), ("stable diffusion", "Stable Diffusion"),
    ("midjourney", "Midjourney"), ("ai绘画", "AI绘画"),
    ("强化学习", "强化学习"), ("自然语言处理", "NLP"), ("nlp", "NLP"),
    ("计算机视觉", "计算机视觉"), ("cv", "计算机视觉"),
    ("rag", "RAG"), ("向量数据库", "向量数据库"),
    ("fine-tune", "微调"), ("微调", "微调"), ("lora", "LoRA"),
    ("agent", "Agent"), ("智能体", "Agent"),
    ("prompt", "Prompt"), ("提示词", "Prompt"),

    # 前端 / 后端
    ("前端", "前端"), ("后端", "后端"), ("全栈", "全栈"),
    ("react", "React"), ("vue", "Vue"), ("next.js", "Next.js"),
    ("nextjs", "Next.js"), ("angular", "Angular"), ("svelte", "Svelte"),
    ("node.js", "Node.js"), ("nodejs", "Node.js"),
    ("spring", "Spring"), ("django", "Django"), ("flask", "Flask"),
    ("fastapi", "FastAPI"), ("express", "Express"),
    ("html", "HTML"), ("css", "CSS"), ("tailwind", "Tailwind"),

    # 数据库 / 基础设施
    ("数据库", "数据库"), ("mysql", "MySQL"), ("postgresql", "PostgreSQL"),
    ("redis", "Redis"), ("mongodb", "MongoDB"), ("sqlite", "SQLite"),
    ("docker", "Docker"), ("kubernetes", "Kubernetes"), ("k8s", "Kubernetes"),
    ("linux", "Linux"), ("nginx", "Nginx"), ("云服务", "云服务"),
    ("微服务", "微服务"), ("分布式", "分布式"),

    # 算法 / 数据结构
    ("算法", "算法"), ("数据结构", "数据结构"),
    ("leetcode", "LeetCode"), ("力扣", "LeetCode"),
    ("动态规划", "动态规划"), ("二叉树", "二叉树"),
    ("排序", "排序算法"), ("图论", "图论"),

    # 框架 / 工具
    ("git", "Git"), ("github", "GitHub"), ("ci/cd", "CI/CD"),
    ("webpack", "Webpack"), ("vite", "Vite"), ("bun", "Bun"),
    ("pytorch", "PyTorch"), ("tensorflow", "TensorFlow"),
    ("keras", "Keras"), ("scikit-learn", "Scikit-learn"),
    ("pandas", "Pandas"), ("numpy", "NumPy"),

    # 内容类型
    ("教程", "教程"), ("入门", "入门"), ("入门教程", "教程"),
    ("实战", "实战"), ("项目", "项目实战"),
    ("面试", "面试"), ("面经", "面试"),
    ("源码", "源码分析"), ("源码分析", "源码分析"),
    ("原理", "原理"), ("架构", "架构"),
    ("性能优化", "性能优化"), ("优化", "优化"),
    ("最佳实践", "最佳实践"), ("设计模式", "设计模式"),
    ("安全", "安全"), ("网络安全", "安全"),

    # 其他技术
    ("爬虫", "爬虫"), ("逆向", "逆向工程"),
    ("区块链", "区块链"), ("web3", "Web3"),
    ("游戏", "游戏开发"), ("unity", "Unity"), ("unreal", "Unreal"),
    ("安卓", "Android"), ("android", "Android"),
    ("ios", "iOS"), ("flutter", "Flutter"),
    ("electron", "Electron"), ("桌面应用", "桌面应用"),
    ("api", "API"), ("restful", "RESTful"), ("graphql", "GraphQL"),
    ("websocket", "WebSocket"), ("grpc", "gRPC"),
    ("测试", "测试"), ("自动化测试", "自动化测试"),
    ("devops", "DevOps"), ("运维", "运维"),
]

# 平台名 → 平台标识
_PLATFORM_KEYWORDS = {
    "bilibili": "bilibili", "b站": "bilibili", "bilibili.com": "bilibili",
    "youtube": "youtube", "youtu.be": "youtube",
    "douyin": "douyin", "抖音": "douyin",
    "tiktok": "tiktok",
    "xiaohongshu": "xiaohongshu", "小红书": "xiaohongshu",
}


def extract_tags(title: str, summary: str = "", url: str = "") -> list[str]:
    """从标题和摘要中提取 3-5 个标签。

    策略：关键词匹配 + 平台识别 + 内容类型识别。
    """
    text = f"{title} {summary}".lower()
    tags = []
    seen = set()

    # 1. 关键词匹配（按优先级，先匹配的不重复）
    for keyword, tag in _KEYWORD_TAGS:
        if len(tags) >= 5:
            break
        if keyword in text and tag not in seen:
            tags.append(tag)
            seen.add(tag)

    # 2. 平台识别（从 URL 或文本）
    url_lower = url.lower()
    for kw, platform in _PLATFORM_KEYWORDS.items():
        if kw in url_lower or kw in text:
            if platform not in seen:
                tags.append(platform)
                seen.add(platform)
            break

    # 3. 不足 3 个标签时，不再盲切中文词（会产生垃圾标签），有多少返回多少

    return tags[:5]


def detect_platform(url: str, extractor: str = "") -> str:
    """从 URL 或 yt-dlp extractor 名识别平台。"""
    url_lower = url.lower()
    for kw, platform in _PLATFORM_KEYWORDS.items():
        if kw in url_lower:
            return platform
    # 从 yt-dlp extractor 名
    ext_lower = extractor.lower()
    if "bilibili" in ext_lower:
        return "bilibili"
    if "youtube" in ext_lower:
        return "youtube"
    if "douyin" in ext_lower:
        return "douyin"
    if "tiktok" in ext_lower:
        return "tiktok"
    if "xiaohongshu" in ext_lower:
        return "xiaohongshu"
    return ""
