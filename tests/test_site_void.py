"""A void tape row never shows a DEX-derived number on the site (its values stay in tape.csv as measured)."""

from callrec.site import _tape_table


def _row(**kw):
    base = {"token": "0xabc", "frozen_ref": "50.0", "twap_last_hour": "3.4025678654032517e+40", "reopen_ref": "51.0",
            "gap_bps": "890393.26", "reopen_bps": "169.64", "tape_error_bps": "-890223.61", "max_abs_gap_bps": "",
            "swaps_span": "3", "volume_span_usd": "12", "alt_247_ref": "", "void": "dex_thin"}
    base.update(kw)
    return base


def test_void_row_hides_dex_values():
    html = _tape_table([_row()], {"0xabc": "CRCLc"})
    assert "890" not in html and "e+40" not in html and "3.40" not in html
    assert "dex_thin" in html and "+170" in html  # the reason and the reference move still show


def test_usable_row_shows_dex_values():
    html = _tape_table([_row(void="", twap_last_hour="50.5", gap_bps="100", tape_error_bps="69.64")], {"0xabc": "CRCLc"})
    assert "50.50" in html and "+100" in html
