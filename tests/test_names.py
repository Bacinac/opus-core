from opus_core.names import croatian


def ordered(*titles: str) -> list[str]:
    return sorted(titles, key=croatian)


def test_the_croatian_alphabet():
    assert ordered("Žmegač", "Zagreb", "Šehić", "Sutra", "Ćevapi", "Čavle", "Cesta", "Dora") == [
        "Cesta", "Čavle", "Ćevapi", "Dora", "Sutra", "Šehić", "Zagreb", "Žmegač"]


def test_digraphs_are_letters():
    assert ordered("Njegoš", "Nož", "Ljubav", "Lutka", "Džungla", "Dubrava", "Đakovo") == [
        "Dubrava", "Džungla", "Đakovo", "Lutka", "Ljubav", "Nož", "Njegoš"]


def test_numbers_are_numbers():
    assert ordered("1917", "300", "2001: A Space Odyssey", "12 Angry Men") == [
        "12 Angry Men", "300", "1917", "2001: A Space Odyssey"]
    assert ordered("123456789012345678901234", "99") == ["99", "123456789012345678901234"]
    assert croatian("007") == croatian("7")


def test_digits_that_are_not_ascii_do_not_break_the_shelf():
    assert croatian("Alien³")
    assert croatian("٣ Arabic three")
    assert ordered("Alien³", "Alien", "Aliens") == ["Alien", "Aliens", "Alien³"]


def test_punctuation_before_letters_and_other_scripts_after():
    assert ordered("Ωmega", "Abba", "...And Justice") == ["...And Justice", "Abba", "Ωmega"]


def test_the_english_article_is_not_what_a_name_files_under():
    assert ordered("Dubioza Kolektiv", "The Doors", "Dalibor Brun", "Theodora", "the the") == [
        "Dalibor Brun", "The Doors", "Dubioza Kolektiv", "the the", "Theodora"]
    assert croatian("The Doors") == croatian("Doors")
