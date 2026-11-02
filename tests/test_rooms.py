import unittest

from src.main import BASE_URL, Room, extract_rooms


def room_row(room_id="14831", floor=" 3階\n ", columns=10):
    values = ["", "", "301", floor, "1LDK", "45.00m²", "150,000円", "5,000円", "300,000円", "150,000円"]
    cells = "".join(f"<td>{value}</td>" for value in values[:columns])
    return f'<tr>{cells}<td><a href="/bukken/?detail=1361&amp;add={room_id}&amp;view=1">詳細</a></td></tr>'


def table(*rows):
    return '<table class="result_article_table_detail"><tr><th>空室</th></tr>' + "".join(rows) + "</table>"


class ExtractRoomsTests(unittest.TestCase):
    def test_extracts_all_fields_and_normalizes_text(self):
        self.assertEqual(extract_rooms(table(room_row())), [Room(
            room_id="14831", floor="3階", layout="1LDK", area="45.00m²",
            rent="150,000円", management_fee="5,000円", deposit="300,000円",
            key_money="150,000円",
            detail_url=BASE_URL + "/bukken/?detail=1361&add=14831&view=1",
        )])

    def test_missing_or_empty_table(self):
        for html in ("", "<table><tr><td>Other table</td></tr></table>", table()):
            with self.subTest(html=html):
                self.assertEqual(extract_rooms(html), [])

    def test_skips_invalid_rows_and_preserves_order_and_duplicates(self):
        html = table(
            '<tr><td>No link</td></tr>',
            room_row("short", columns=3),
            '<tr><td><a href="">Empty link</a></td></tr>',
            room_row("2"), room_row("1"), room_row("2"),
        )
        self.assertEqual([room.room_id for room in extract_rooms(html)], ["2", "1", "2"])

    def test_uses_only_first_matching_table(self):
        self.assertEqual([room.room_id for room in extract_rooms(table(room_row("1")) + table(room_row("2")))], ["1"])

    def test_preserves_absolute_detail_url(self):
        html = table(room_row()).replace('/bukken/?detail=', BASE_URL + '/bukken/?detail=')
        self.assertEqual(extract_rooms(html)[0].detail_url, BASE_URL + "/bukken/?detail=1361&add=14831&view=1")


if __name__ == "__main__":
    unittest.main()
