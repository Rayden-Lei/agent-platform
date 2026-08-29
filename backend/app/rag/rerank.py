"""检索重排：默认轻量启发式（词法命中加权），接口独立，可替换为 LLM/外部 rerank 服务。"""
import re


def extract_keywords(query: str) -> list:
    """从查询中提取关键词：英文/数字词 + 中文片段(2-gram)。"""
    keywords = set()
    for w in re.findall(r"[a-zA-Z0-9]+", query):
        if len(w) >= 2:
            keywords.add(w.lower())
    for seg in re.findall(r"[\u4e00-\u9fa5]+", query):
        if len(seg) <= 4:
            keywords.add(seg)
        else:
            for i in range(len(seg) - 1):
                keywords.add(seg[i:i + 2])
    return list(keywords)


def rerank(query: str, candidates: list, keywords: list = None) -> list:
    """对候选做轻量重排，返回按 score 降序的新列表。

    默认启发式：query 词元在 content 中的覆盖率（词法命中）与既有混合分各占 50% 融合。
    函数保持独立、可替换——未来可换成 LLM 打分或外部 rerank 服务。
    """
    if not candidates:
        return []
    keywords = keywords or extract_keywords(query)
    ranked = []
    for c in candidates:
        content = (c.get("content") or "").lower()
        hits = [kw for kw in keywords if kw.lower() in content]
        coverage = len(hits) / len(keywords) if keywords else 0.0
        length_bonus = min(sum(len(kw) for kw in hits) / 100.0, 1.0)
        lexical = coverage * 0.8 + length_bonus * 0.2
        base = float(c.get("score", 0.0))
        item = dict(c)
        item["lexical_score"] = round(lexical, 4)
        item["matched_keywords"] = hits
        item["score"] = round(base * 0.5 + lexical * 0.5, 4)
        ranked.append(item)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
