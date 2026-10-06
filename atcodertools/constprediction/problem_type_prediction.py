import re

from bs4 import BeautifulSoup


def predict_problem_type(html):
    """Recognize explicit statement wording, without inferring a validator's logic."""
    soup = BeautifulSoup(html, "html.parser")
    statement = soup.select_one("#task-statement") or soup
    for element in statement.select("script, style"):
        element.decompose()
    text = " ".join(statement.get_text(" ", strip=True).split())
    compact = text.replace(" ", "")
    japanese_interactive = re.search(r"インタラクティブ(?:な)?問題", compact)
    if japanese_interactive and not re.search(r"インタラクティブ(?:な)?問題では(?:ない|ありません)", compact):
        return "interactive"
    if re.search(r"(?:this is an interactive problem|this problem is interactive|this problem is an interactive problem)",
                 text, re.IGNORECASE):
        return "interactive"
    if re.search(r"(?:答え|解|出力|方法|構築方法)[^。]{0,40}複数[^。]{0,100}(?:どれ|いずれ|どの|任意)[^。]{0,50}(?:正解|出力)", compact):
        return "output_validation"
    if re.search(r"(?:multiple|more than one) (?:possible |valid |correct )?(?:answers|solutions|outputs)[^.]{0,150}"
                 r"(?:print any|output any|any[^.]{0,60}accepted)", text, re.IGNORECASE):
        return "output_validation"
    return "batch"
