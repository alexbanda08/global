
def f2_should_fire(book_up_ask: float, book_up_ask_size: float,
                    book_down_ask: float, book_down_ask_size: float,
                    binance_ret_60s: float,
                    offset_from_slot_start_s: int) -> tuple[bool, str | None]:
    """Return (fire, direction). Direction is contrarian to binance_ret_60s."""
    sum_asks = book_up_ask + book_down_ask
    max_asz = max(book_up_ask_size, book_down_ask_size)

    if max_asz < 200:
        return False, None
    if offset_from_slot_start_s < 180:
        return False, None
    if sum_asks < 1.005:
        return False, None
    # Skip if binance signal too weak (sub-bp)
    if abs(binance_ret_60s) < 1e-4:
        return False, None

    # Contrarian direction: fade binance recent move
    direction = "Down" if binance_ret_60s > 0 else "Up"
    return True, direction
