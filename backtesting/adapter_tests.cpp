#include "strategy_adapter.h"
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace {
int checks = 0;
void require(bool ok, const char* name) {
    ++checks;
    if (!ok) throw std::runtime_error(name);
}
void checkNear(double actual, double expected, const char* name) {
    require(std::abs(actual - expected) < 1e-10, name);
}
Bar bar(double open, double high, double low, double close) {
    return Bar{"fixture", high, low, open, close,
               DecimalFunctions::doubleToDecimal(close),
               DecimalFunctions::doubleToDecimal(1000), 1};
}
std::int64_t epoch(const char* zone, int year, unsigned month, unsigned day,
                   int hour, int minute, int second) {
    using namespace std::chrono;
    const auto local = local_days{std::chrono::year{year}/month/day} +
                       hours{hour} + minutes{minute} + seconds{second};
    return zoned_time{locate_zone(zone), local}.get_sys_time().time_since_epoch().count();
}

void timeTests() {
    for (unsigned month : {1u, 7u}) {
        require(!bt::validTime(epoch("Asia/Jerusalem", 2026, month, 12, 16, 35, 9)), "entry lower bound excluded");
        require(bt::validTime(epoch("Asia/Jerusalem", 2026, month, 12, 16, 35, 10)), "entry lower bound included");
        require(bt::validTime(epoch("Asia/Jerusalem", 2026, month, 12, 17, 0, 59)), "entry last second included");
        require(!bt::validTime(epoch("Asia/Jerusalem", 2026, month, 12, 17, 1, 0)), "entry upper bound excluded");
    }
    require(!bt::validTime(epoch("America/New_York", 2026, 3, 16, 9, 35, 10)), "US/Israel DST mismatch retained");
    require(bt::validTime(epoch("America/New_York", 2026, 4, 6, 9, 35, 10)), "matching DST opening time");
}

void indicatorAndQuantityTests(DataFetcher& fetcher) {
    std::vector<Bar> daily(15, bar(100, 102, 98, 100));
    checkNear(fetcher.getAtr(daily), 4.0, "ATR first fourteen TR seed");
    daily.push_back(bar(100, 104, 96, 100));
    checkNear(fetcher.getAtr(daily), 4.0 + 4.0 * (2.0 / 15.0), "ATR uses EMA alpha two fifteenths");
    std::vector<Bar> five;
    for (int i = 1; i <= 200; ++i) five.push_back(bar(i, i + 1, i - 1, i));
    checkNear(fetcher.getSma10(five), 195.5, "SMA10 includes last supplied close");
    checkNear(fetcher.getSma20(five), 190.5, "SMA20 exact window");
    checkNear(fetcher.getSma200(five), 100.5, "SMA200 exact window");
    five[five.size() - 2] = bar(101, 110, 100, 108);
    five.back() = bar(200, 300, 1, 200);
    require(fetcher.validBar(five) == "GreenBar", "valid candle uses second-last at 70 percent body");
    checkNear(fetcher.getCandleLow(five), 100, "sizing low is second-last");
    checkNear(fetcher.getCandleHigh(five), 110, "sizing high is second-last");
    require(bt::quantity(fetcher, five, 105, "BUY") == 6, "long sizing fixed thirty dollar risk");
    require(bt::quantity(fetcher, five, 105, "SELL") == 6, "short sizing fixed thirty dollar risk");
    require(bt::quantity(fetcher, five, 107, "BUY") == 4, "quantity floors fractional shares");
    require(bt::quantity(fetcher, five, 100, "BUY") == 0, "zero long distance rejected");
    require(bt::quantity(fetcher, five, 110, "SELL") == 0, "zero short distance rejected");
    require(bt::quantity(fetcher, five, 100, "SELL") == 0, "original last price equals low guard retained for short");
    require(bt::quantity(fetcher, five, std::numeric_limits<double>::infinity(), "BUY") == 0, "nonfinite sizing rejected");
    require(bt::quantity(fetcher, five, 100 + 1e-12, "BUY") == 0, "integer overflow sizing rejected");
    five[five.size() - 2] = bar(108, 110, 100, 101);
    require(fetcher.validBar(five) == "RedBar", "red candle threshold");
    five[five.size() - 2] = bar(101, 110, 100, 107);
    require(fetcher.validBar(five) == "false", "sub-threshold candle rejected");
}

void signalTests(DataFetcher& fetcher, std::vector<Bar>& realtime) {
    // Exactly fourteen true ranges keeps the equality fixture binary-exact;
    // a long EMA recurrence can drift above ten through floating-point rounding.
    std::vector<Bar> daily(15, bar(100, 105, 95, 100));
    std::vector<Bar> five(200, bar(90, 91, 89, 90));
    for (std::size_t i = 180; i < five.size(); ++i) five[i] = bar(100, 101, 99, 100);
    five[five.size() - 2] = bar(99, 101, 99, 101);
    realtime = {bar(102, 102, 102, 102)};
    const auto time = epoch("Asia/Jerusalem", 2026, 7, 12, 16, 35, 10);
    OrderInstructions instructions{};
    require(bt::signal(instructions, fetcher, daily, five, realtime, time) && instructions.action == "BUY", "original long entry through full adapter");
    realtime.back().close = 104;
    require(!bt::signal(instructions, fetcher, daily, five, realtime, time), "exact forty percent ATR boundary excluded");
    realtime.back().close = 102;
    require(!bt::signal(instructions, fetcher, daily, five, realtime, time - 1), "entry time passed to original signal");
    five[five.size() - 2] = bar(100, 101, 99, 100);
    require(!bt::signal(instructions, fetcher, daily, five, realtime, time), "doji rejects signal");
    for (std::size_t i = 0; i < 180; ++i) five[i] = bar(110, 111, 109, 110);
    five[five.size() - 2] = bar(101, 101, 99, 99);
    realtime.back().close = 98;
    require(bt::signal(instructions, fetcher, daily, five, realtime, time) && instructions.action == "SELL", "original short entry through full adapter");
    require(!bt::signal(instructions, fetcher, {}, five, realtime, time), "missing history rejects signal");
}

void exitTests() {
    require(bt::exitSignal("BUY", 99, 100), "long exits below SMA10");
    require(!bt::exitSignal("BUY", 100, 100), "long equality does not exit");
    require(!bt::exitSignal("BUY", 101, 100), "long above SMA10 remains open");
    require(bt::exitSignal("SELL", 101, 100), "short exits above SMA10");
    require(!bt::exitSignal("SELL", 100, 100), "short equality does not exit");
    require(!bt::exitSignal("SELL", 99, 100), "short below SMA10 remains open");
}
}

int main() {
    std::ostringstream captured;
    auto* original = std::cout.rdbuf(captured.rdbuf());
    try {
        Contract contract;
        contract.symbol = "FIXTURE";
        std::vector<Bar> realtime;
        DataFetcher fetcher(0, &realtime, contract);
        timeTests();
        indicatorAndQuantityTests(fetcher);
        signalTests(fetcher, realtime);
        exitTests();
        std::cout.rdbuf(original);
        std::cout << "PASS: " << checks << " adapter checks; fixtures are synthetic, not historical performance.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cout.rdbuf(original);
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}

