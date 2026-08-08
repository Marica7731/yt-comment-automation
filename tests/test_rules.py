"""rules.py 统一规则单元测试（对应 RULES.md R01-R17）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import rules  # noqa: E402


def test_r01_fullwidth_digits():
    assert rules.normalize_fullwidth("１・２・３") == "1・2・3"
    assert rules.normalize_fullwidth("オリジナル１（少し）") == "オリジナル1（少し）"


def test_r10_fullwidth_ascii():
    assert rules.normalize_fullwidth("ＬＩＦＥ") == "LIFE"
    assert rules.normalize_fullwidth("０１. RE:I AM") == "01. RE:I AM"


def test_r02_numeral_prefix_protects_8_32():
    assert rules.strip_leading_numeral_prefix("01. 'PPPP' / TAK") == "'PPPP' / TAK"
    assert rules.strip_leading_numeral_prefix("8.32") == "8.32"  # 纯数字歌名保护


def test_r03_fullwidth_bracket_numeral():
    assert rules.strip_leading_fullwidth_bracket_numeral("〔10〕 JANE DOE") == "JANE DOE"


def test_r04_list_decoration():
    assert rules.strip_list_decoration_prefix("└  Blue Jeans / HANA") == "Blue Jeans / HANA"


def test_r05_single_quotes():
    assert rules.strip_surrounding_single_quotes("'PPPP'") == "PPPP"
    # Don't say "lazy" 不以单引号开头，内部双引号不删
    assert rules.strip_surrounding_single_quotes("Don't say \"lazy\"") == "Don't say \"lazy\""


def test_r06_transliteration_paren():
    assert rules.strip_parenthetical_transliteration("絶頂讃歌 (Zetchou Sanka | Orgasm Anthem)") == "絶頂讃歌"
    assert rules.strip_parenthetical_transliteration("ryo(supercell)") == "ryo(supercell)"


def test_r07_performance_notes():
    assert rules.strip_performance_note_parens("ロビンソン（少し）") == "ロビンソン"
    assert rules.strip_performance_note_parens("瞬き（1番のみ）") == "瞬き"
    assert rules.strip_performance_note_parens("ウィステリア（ちょっと）") == "ウィステリア"
    assert rules.strip_performance_note_parens("エイリアンズ（練習）") == "エイリアンズ"
    assert rules.strip_performance_note_parens("Lemon（うろ覚え）") == "Lemon"


def test_r08_noise_line():
    assert rules.is_noise_line("締め")
    assert rules.is_noise_line("1,2曲リクエスト")
    assert not rules.is_noise_line("リクエスト")


def test_r09_protected_titles():
    assert rules.has_protected_title("Don't say \"lazy\"")
    assert rules.has_protected_title("ryo(supercell)")
    assert rules.has_protected_title("DISH//")
    assert rules.has_protected_title("ツインテールは20歳まで♡")
    assert not rules.has_protected_title("バラライカ")


def test_r13_track_number_prefix():
    assert rules.strip_leading_numeral_prefix("01. RE:I AM") == "RE:I AM"
    assert rules.strip_leading_numeral_prefix("16. 奏（かなで）") == "奏（かなで）"


def test_r14_furigana_parens():
    assert rules.strip_furigana_parens("奏（かなで）") == "奏"
    assert rules.strip_furigana_parens("涼宮ハルヒ(平野綾)") == "涼宮ハルヒ(平野綾)"  # 括号含汉字不删


def test_r15_release_date():
    assert rules.strip_release_date_parens("Aimer (2019/05/05)") == "Aimer"
    assert rules.strip_release_date_parens("橋本潮 [2018年]") == "橋本潮"


def test_apply_song_cleanup_integration():
    # 组合：序号 + 表演备注 + 译文括号
    assert rules.apply_song_cleanup("01. ロビンソン（少し）/スピッツ") == "ロビンソン / スピッツ"
    assert rules.apply_song_cleanup("2. 絶頂讃歌 (Zetchou Sanka | Orgasm Anthem) / 和ぬか") == "絶頂讃歌 / 和ぬか"
    # 纯数字歌名保护
    assert rules.apply_song_cleanup("8.32 / *Luna") == "8.32 / *Luna"
    # 受保护标题不删
    assert rules.apply_song_cleanup("Don't say \"lazy\" - 桜高軽音部") == "Don't say \"lazy\" - 桜高軽音部"
    # 发行日期删除
    assert rules.apply_song_cleanup("Aimer (2019/05/05)") == "Aimer"
