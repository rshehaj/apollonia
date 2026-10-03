from apollonia.normalize import fold_accents, fold_key, keyword_terms


def test_fold_accents_removes_albanian_diacritics() -> None:
    assert fold_accents("Skënderbeu dhe çështja ËÇ") == "Skenderbeu dhe ceshtja EC"


def test_keyword_terms_drop_stopwords_and_punctuation() -> None:
    assert keyword_terms("Kur u themelua Lidhja e Prizrenit?") == [
        "themelua",
        "lidhja",
        "prizrenit",
    ]


def test_keyword_terms_fold_accents_and_keep_numbers() -> None:
    assert keyword_terms("Çfarë ndodhi në 1912?") == ["ndodhi", "1912"]


def test_keyword_terms_strip_tsquery_operators_and_duplicates() -> None:
    assert keyword_terms("Prizren & | ! ( ) :* 'Prizren' <-> x") == ["prizren"]


def test_keyword_terms_of_stopwords_only_is_empty() -> None:
    assert keyword_terms("Kur ishte?") == []
    assert keyword_terms("   ") == []


def test_fold_key_folds_accents_and_case() -> None:
    assert fold_key("Shënime") == fold_key("SHENIME") == "shenime"
    assert fold_key("Straße") == "strasse"
