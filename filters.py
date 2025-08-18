from rapidfuzz import fuzz

SYNONYMS = {
    "питон": ["python"],
    "дистанционно": ["удаленно", "удалённо", "remote"],
    "без опыта": ["junior", "начинающий", "intern"],
    "офис": ["офисе", "офиса"],
    "гибрид": ["гибридно", "hybrid"],
    "стажировка": ["internship", "стажёр"],
    "зарплата": ["оплата", "salary", "зп"],
    "fullstack": ["full stack", "фулстек"],
    "backend": ["бэкенд", "бекенд"],
    "frontend": ["фронтенд"]
}

def normalize(word: str):
    word = word.lower().strip()
    return list(set([word] + SYNONYMS.get(word, [])))  # Убираем дубликаты

def text_matches_filters(text: str, filters: list[list[str]]) -> bool:
    text = text.lower()

    for group in filters:
        found = False
        for word in group:
            variants = normalize(word)
            for variant in variants:
                if variant.lower() in text:
                    found = True
                    break
            if found:
                break
        if not found:
            return False
    return True