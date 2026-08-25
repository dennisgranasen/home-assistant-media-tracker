"""Regression tests for the official Guldbaggen nominee cards."""

from custom_components.media_watch.award_adapters.guldbaggen import (
    _CurrentNomineeParser,
)


def test_current_nominee_parser_reads_structural_winner_and_film_title() -> None:
    parser = _CurrentNomineeParser()
    parser.feed(
        """
        <div class="awardRow">
          <h2>Bästa film</h2>
          <div class="text"><h3>Nominerad film</h3></div>
          <div class="text isWinner"><h3>Vinnarfilmen</h3><p>VINNARE</p></div>
        </div>
        <div class="awardRow">
          <h2>Bästa regi</h2>
          <div class="text isWinner">
            <h3>Regissörens namn</h3><h4>för Vinnarfilmen</h4>
          </div>
        </div>
        """
    )

    assert parser.records == [
        {
            "media_type": "movie",
            "category": "Bästa film",
            "title": "Nominerad film",
            "title_candidates": ["Nominerad film"],
            "recipients": [],
            "winner": False,
        },
        {
            "media_type": "movie",
            "category": "Bästa film",
            "title": "Vinnarfilmen",
            "title_candidates": ["Vinnarfilmen"],
            "recipients": [],
            "winner": True,
        },
        {
            "media_type": "movie",
            "category": "Bästa regi",
            "title": "Vinnarfilmen",
            "title_candidates": ["Vinnarfilmen"],
            "recipients": ["Regissörens namn"],
            "winner": True,
        },
    ]


def test_archive_cards_preserve_year_and_winner_class() -> None:
    parser = _CurrentNomineeParser()
    parser.feed(
        """
        <div class="awardRow">
          <h2>Bästa film</h2><h3>2024</h3>
          <div class="awardList">
            <div class="nominee"><div class="text">
              <h3><a>Nominerad film</a></h3>
            </div></div>
            <div class="nominee"><div class="text isWinner">
              <h3><a>Passage</a></h3>
            </div></div>
          </div>
        </div>
        """
    )

    assert [record["award_year"] for record in parser.records] == [
        2024,
        2024,
    ]
    assert [record["winner"] for record in parser.records] == [
        False,
        True,
    ]
