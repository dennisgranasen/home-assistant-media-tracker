"""Regression tests for the official HKFAA HTML format."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.media_watch.award_adapters.hong_kong_film_awards import (
    HongKongFilmAwardsAdapter,
)
from custom_components.media_watch.award_adapters.web_common import (
    _TableTextParser,
)


def test_ordered_list_nominees_are_parsed_and_winner_is_marked() -> None:
    html = """
    <table>
      <tr>
        <th>獎項</th><th>候選者</th><th>得獎者</th>
      </tr>
      <tr>
        <td>最佳電影<br>Best Film</td>
        <td>
          <ol>
            <li><strong>世外ANOTHER WORLD</strong><br>
                Presented by: Point Five Creations</li>
            <li><strong>尋秦記BACK TO THE PAST</strong><br>
                Presented by: One Cool Film Production</li>
          </ol>
        </td>
        <td>尋秦記BACK TO THE PAST</td>
      </tr>
    </table>
    """
    parser = _TableTextParser(number_ordered_list_items=True)
    parser.feed(html)

    records = HongKongFilmAwardsAdapter._parse_rows(
        parser.rows,
        ceremony=44,
    )

    assert len(records) == 2
    assert [record["category"] for record in records] == [
        "Best Film",
        "Best Film",
    ]
    assert [record["winner"] for record in records] == [False, True]
    assert records[0]["title"] == "ANOTHER WORLD"
    assert records[1]["title"] == "BACK TO THE PAST"


def test_repeated_acronym_in_bilingual_title_is_not_duplicated() -> None:
    candidates = HongKongFilmAwardsAdapter._title_candidates(
        "1. 再見UFO CIAO UFO",
        "Best Film",
    )

    assert candidates[-1] == "CIAO UFO"


def test_person_category_uses_english_recipient_and_only_film_as_title() -> None:
    html = """
    <table><tr>
      <td>最佳導演<br>Best Director</td>
      <td><ol><li>梁栢堅（再見UFO）<br>
          Patrick Leung Pak Kin (CIAO UFO)</li></ol></td>
      <td>梁栢堅（再見UFO）<br>
          Patrick Leung Pak Kin (CIAO UFO)</td>
    </tr></table>
    """
    parser = _TableTextParser(number_ordered_list_items=True)
    parser.feed(html)

    records = HongKongFilmAwardsAdapter._parse_rows(
        parser.rows,
        ceremony=44,
    )

    assert len(records) == 1
    assert records[0]["title_candidates"] == ["CIAO UFO"]
    assert records[0]["recipients"] == ["Patrick Leung Pak Kin"]
    assert records[0]["person_aliases"] == {
        "梁栢堅": "Patrick Leung Pak Kin"
    }
    assert records[0]["winner"] is True

    aggregated = asyncio.run(
        HongKongFilmAwardsAdapter(
            SimpleNamespace(
                data={
                    "media_watch_award_http_cache": {
                        f"table:numbered:{HongKongFilmAwardsAdapter._url(44)}": parser.rows,
                    }
                }
            )
        ).async_filter_titles(
            media_type="movie",
            year_from=2026,
            year_to=2026,
            category="Best Director",
            status="winner",
        )
    )
    assert aggregated[0]["title"] == "CIAO UFO"
    assert aggregated[0]["recipients"] == ["Patrick Leung Pak Kin"]
    assert aggregated[0]["person_aliases"] == {
        "梁栢堅": "Patrick Leung Pak Kin"
    }


def test_best_film_results_include_english_person_aliases() -> None:
    html = """
    <table>
      <tr><td>最佳電影<br>Best Film</td>
        <td><ol><li>再見UFO CIAO UFO</li></ol></td>
        <td>再見UFO CIAO UFO</td></tr>
      <tr><td>最佳導演<br>Best Director</td>
        <td><ol><li>梁栢堅（再見UFO）<br>
          Patrick Leung Pak Kin (CIAO UFO)</li></ol></td>
        <td>梁栢堅（再見UFO）<br>
          Patrick Leung Pak Kin (CIAO UFO)</td></tr>
      <tr><td>最佳男主角<br>Best Actor</td>
        <td><ol><li>郭富城（再見UFO）<br>
          Aaron Kwok (CIAO UFO)</li></ol></td>
        <td>郭富城（再見UFO）<br>Aaron Kwok (CIAO UFO)</td></tr>
    </table>
    """
    parser = _TableTextParser(number_ordered_list_items=True)
    parser.feed(html)
    url = HongKongFilmAwardsAdapter._url(44)
    adapter = HongKongFilmAwardsAdapter(
        SimpleNamespace(
            data={
                "media_watch_award_http_cache": {
                    f"table:numbered:{url}": parser.rows,
                }
            }
        )
    )

    result = asyncio.run(
        adapter.async_filter_titles(
            media_type="movie",
            year_from=2026,
            year_to=2026,
            category="Best Film",
            status="winner",
        )
    )

    assert result[0]["person_aliases"] == {
        "梁栢堅": "Patrick Leung Pak Kin",
        "郭富城": "Aaron Kwok",
    }


def test_adapter_uses_numbered_table_variant_for_winner_filter() -> None:
    html = """
    <table><tr>
      <td>最佳電影<br>Best Film</td>
      <td><ol><li>世外ANOTHER WORLD</li><li>尋秦記BACK TO THE PAST</li></ol></td>
      <td>尋秦記BACK TO THE PAST</td>
    </tr></table>
    """
    parser = _TableTextParser(number_ordered_list_items=True)
    parser.feed(html)
    url = HongKongFilmAwardsAdapter._url(44)
    hass = SimpleNamespace(
        data={
            "media_watch_award_http_cache": {
                f"table:numbered:{url}": parser.rows,
            }
        }
    )
    adapter = HongKongFilmAwardsAdapter(hass)

    result = asyncio.run(
        adapter.async_filter_titles(
            media_type="movie",
            year_from=2026,
            year_to=2026,
            category="Best Film",
            status="winner",
        )
    )

    assert len(result) == 1
    assert result[0]["title"] == "BACK TO THE PAST"
    assert result[0]["wins"] == 1


def test_plain_table_parser_does_not_synthesize_list_numbers() -> None:
    parser = _TableTextParser()
    parser.feed("<table><tr><td><ol><li>Film A</li></ol></td></tr></table>")

    assert parser.rows == [["Film A"]]


def test_winner_only_chinese_rows_are_preserved() -> None:
    html = """
    <table>
      <tr><th>獎項</th><th>得獎者</th></tr>
      <tr><td>最佳電影</td><td>父子情</td></tr>
      <tr><td>最佳導演</td><td>方育平 (父子情)</td></tr>
    </table>
    """
    parser = _TableTextParser(number_ordered_list_items=True)
    parser.feed(html)

    records = HongKongFilmAwardsAdapter._parse_rows(
        parser.rows,
        ceremony=1,
    )

    assert [record["category"] for record in records] == [
        "Best Film",
        "Best Director",
    ]
    assert [record["title"] for record in records] == [
        "父子情",
        "父子情",
    ]
    assert all(record["winner"] for record in records)
