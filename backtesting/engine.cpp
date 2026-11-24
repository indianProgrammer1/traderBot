// Offline replay only. No EClientSocket, broker connection, or order submission API.
#include "strategy_adapter.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <streambuf>
#include <string>
#include <tuple>
#include <utility>
#include <vector>
#include <Windows.h>

namespace {
using Epoch = std::int64_t;
using namespace std::chrono;
constexpr Epoch Never = (std::numeric_limits<Epoch>::max)();
const std::array<std::string, 10> Universe{
    "TSLA", "NFLX", "CRWD", "MRNA", "AMD", "NVDA", "AAPL", "ROKU", "PDD", "MSFT"};

struct Options {
    std::string data, out;
    Epoch start = 0, end = 0;
    double capital = 4200, leverage = 2.5, commission = .005, minimumCommission = 1;
    double slippageBps = 1, halfSpreadBps = 1, maxParticipation = 1;
    bool synthetic = false;
};

double number(const std::string& value) {
    std::size_t used = 0;
    double n = std::stod(value, &used);
    if (used != value.size() || !std::isfinite(n)) throw std::runtime_error("Invalid number: " + value);
    return n;
}
Epoch integer(const std::string& value) {
    std::size_t used = 0;
    Epoch n = std::stoll(value, &used);
    if (used != value.size()) throw std::runtime_error("Invalid integer: " + value);
    return n;
}
Options options(int argc, char** argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--synthetic-test") { o.synthetic = true; continue; }
        if (i + 1 == argc) throw std::runtime_error("Missing value for " + arg);
        std::string v = argv[++i];
        if (arg == "--data") o.data = v;
        else if (arg == "--out") o.out = v;
        else if (arg == "--start") o.start = integer(v);
        else if (arg == "--end") o.end = integer(v);
        else if (arg == "--capital") o.capital = number(v);
        else if (arg == "--leverage") o.leverage = number(v);
        else if (arg == "--commission-per-share") o.commission = number(v);
        else if (arg == "--min-commission") o.minimumCommission = number(v);
        else if (arg == "--slippage-bps") o.slippageBps = number(v);
        else if (arg == "--half-spread-bps") o.halfSpreadBps = number(v);
        else if (arg == "--max-participation") o.maxParticipation = number(v);
        else throw std::runtime_error("Unknown argument: " + arg);
    }
    if (o.data.empty() || o.out.empty() || o.start <= 0 || o.end <= o.start)
        throw std::runtime_error("Required: --data CSV --out DIR --start UNIX_SECONDS --end UNIX_SECONDS");
    if (o.capital <= 0 || o.leverage < 1 || o.commission < 0 || o.minimumCommission < 0 ||
        o.slippageBps < 0 || o.halfSpreadBps < 0 || o.slippageBps + o.halfSpreadBps >= 10000 ||
        o.maxParticipation <= 0 || o.maxParticipation > 1)
        throw std::runtime_error("Invalid capital, leverage, execution costs, or participation");
    // The supported executable location is backtesting/build/replay.exe. Keep
    // generated output inside this isolated tree, including for direct runs.
    // Resolve lexically, then inspect only paths inside the allowed output
    // tree. weakly_canonical probes ancestor metadata outside a Windows sandbox.
    wchar_t modulePath[32768];
    const auto moduleLength = GetModuleFileNameW(nullptr, modulePath, 32768);
    if (!moduleLength || moduleLength >= 32768) throw std::runtime_error("Cannot determine executable path");
    const auto executable = std::filesystem::path(modulePath).lexically_normal();
    const auto root = executable.parent_path().parent_path();
    const auto output = std::filesystem::absolute(o.out).lexically_normal();
    if (root.filename() != "backtesting")
        throw std::runtime_error("Run the executable from its backtesting/build location");
    auto ri = root.begin(), oi = output.begin();
    for (; ri != root.end() && oi != output.end() && *ri == *oi; ++ri, ++oi) {}
    if (ri != root.end()) throw std::runtime_error("Output directory must remain within backtesting/");
    auto inspected = root;
    auto checkDirectory = [](const std::filesystem::path& path) {
        const DWORD attributes = GetFileAttributesW(path.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES) {
            const DWORD error = GetLastError();
            if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND)
                throw std::runtime_error("Cannot inspect isolated output directory");
        } else if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) {
            throw std::runtime_error("Output path must not traverse a junction or symbolic link");
        }
    };
    checkDirectory(inspected);
    for (; oi != output.end(); ++oi) { inspected /= *oi; checkDirectory(inspected); }
    o.out = output.string();
    return o;
}

sys_days nyDate(Epoch t) {
    static const time_zone* zone = locate_zone("America/New_York");
    auto d = floor<days>(zoned_time{zone, sys_seconds{seconds{t}}}.get_local_time());
    return sys_days{d.time_since_epoch()};
}
sys_days sixMonthsBefore(sys_days date) {
    year_month_day target = year_month_day{date} - months{6};
    if (!target.ok()) target = year_month_day{target.year() / target.month() / last};
    return sys_days{target};
}

struct Row {
    std::string symbol, kind;
    Epoch start = 0, end = 0;
    double open = 0, high = 0, low = 0, close = 0, volume = 0;
    bool rth = false;
    Bar asBar() const {
        Bar b{};
        b.time = std::to_string(start);
        b.open = open; b.high = high; b.low = low; b.close = close;
        b.volume = DecimalFunctions::doubleToDecimal(volume);
        return b;
    }
};

// Streaming parser retains only one group of simultaneous five-second bars.
class Input {
    std::ifstream file;
    std::size_t line = 1;
    std::pair<Epoch, std::string> previous{0, ""};
    std::map<std::pair<std::string, std::string>, Epoch> lastEnd;
public:
    explicit Input(const std::string& path) : file(path) {
        if (!file) throw std::runtime_error("Cannot read data: " + path);
        std::string header;
        std::getline(file, header);
        if (!header.empty() && header.back() == '\r') header.pop_back();
        if (header.starts_with("\xef\xbb\xbf")) header.erase(0, 3);
        if (header != "symbol,start_epoch,end_epoch,open,high,low,close,volume,is_rth,kind")
            throw std::runtime_error("Unexpected CSV header");
    }
    std::optional<Row> read() {
        std::string text;
        if (!std::getline(file, text)) return std::nullopt;
        ++line;
        if (!text.empty() && text.back() == '\r') text.pop_back();
        try {
            std::vector<std::string> f;
            std::istringstream stream(text);
            std::string field;
            while (std::getline(stream, field, ',')) f.push_back(field);
            if (f.size() != 10) throw std::runtime_error("Expected ten CSV columns");
            Row r;
            r.symbol = f[0]; r.start = integer(f[1]); r.end = integer(f[2]);
            r.open = number(f[3]); r.high = number(f[4]); r.low = number(f[5]);
            r.close = number(f[6]); r.volume = number(f[7]); r.kind = f[9];
            if (f[8] != "0" && f[8] != "1") throw std::runtime_error("is_rth must be 0 or 1");
            r.rth = f[8] == "1";
            if (std::find(Universe.begin(), Universe.end(), r.symbol) == Universe.end())
                throw std::runtime_error("Symbol absent from production universe: " + r.symbol);
            if (r.kind != "history1d" && r.kind != "history5m" && r.kind != "realtime5s")
                throw std::runtime_error("Unknown bar kind");
            if (r.start <= 0 || r.end <= r.start || r.low <= 0 || r.high < r.low ||
                r.low > (std::min)(r.open, r.close) || r.high < (std::max)(r.open, r.close) || r.volume < 0)
                throw std::runtime_error("Invalid OHLCV or interval");
            if (r.kind == "realtime5s" && (r.end - r.start != 5 || r.start % 5))
                throw std::runtime_error("Realtime interval must be five seconds on a UTC five-second boundary");
            if (r.kind == "history5m" && (r.end - r.start != 300 || r.start % 300))
                throw std::runtime_error("History5m interval must be 300 seconds on a UTC five-minute boundary");
            if (r.kind != "realtime5s" && !r.rth) throw std::runtime_error("Historical snapshots require RTH bars");
            auto key = std::make_pair(r.end, r.symbol);
            if (key < previous) throw std::runtime_error("Rows must be ordered by end_epoch then symbol");
            auto series = std::make_pair(r.symbol, r.kind);
            if (lastEnd.contains(series) && r.start < lastEnd[series])
                throw std::runtime_error("Duplicate or overlapping bars within series");
            lastEnd[series] = r.end; previous = key;
            return r;
        } catch (const std::exception& e) {
            throw std::runtime_error("CSV line " + std::to_string(line) + ": " + e.what());
        }
    }
};

struct TimedBar { Epoch start; sys_days date; Bar bar; };
struct Position {
    int quantity = 0;
    std::string side;
    Epoch entry = 0;
    double price = 0, fees = 0, slippage = 0, spread = 0;
    std::string entryReason;
};
struct Pending {
    Epoch submitted = 0;
    std::uint64_t id = 0;
    int quantity = 0;
    std::string side;
    bool exit = false;
    double signalPrice = 0;
};
struct Symbol {
    std::string name;
    std::vector<Bar> realtime, dailySnapshot, fiveSnapshot;
    std::deque<TimedBar> daily, five;
    std::unique_ptr<DataFetcher> fetcher;
    std::deque<Pending> pending;
    Position position;
    bool terminated = false, entrySubmitted = false, exitSubmitted = false;
    std::string intendedSide;
    int intendedQuantity = 0;
    double mark = 0, priorVolume = 0;
    Epoch lastComplete = 0, firstRealtime = 0;
    std::uint64_t realtimeRows = 0, gaps = 0;
    explicit Symbol(std::string symbol, int requestId) : name(std::move(symbol)) {
        Contract c; c.symbol = name; c.secType = "STK"; c.currency = "USD"; c.exchange = "SMART";
        fetcher = std::make_unique<DataFetcher>(requestId, &realtime, c);
    }
};

class NullBuffer : public std::streambuf {
    int overflow(int c) override { return traits_type::not_eof(c); }
};
// Production indicator/decision functions print on every evaluation; preserve the
// functions themselves and discard their diagnostics only during offline calls.
class QuietProduction {
    NullBuffer sink;
    std::streambuf* old;
public:
    QuietProduction() : old(std::cout.rdbuf(&sink)) {}
    ~QuietProduction() { std::cout.rdbuf(old); }
};

class Replay {
    Options o;
    Input input;
    std::map<std::string, std::unique_ptr<Symbol>> symbols;
    std::optional<Row> lookahead;
    std::vector<Row> upcoming, active;
    std::ofstream trades, equityFile, orders;
    double cash, realized = 0, fees = 0, slip = 0, spread = 0, peak, maxDrawdown = 0, maxDrawdownPct = 0;
    int producerCash = 10500;
    std::uint64_t nextOrder = 1, calls = 0, signals = 0, rejected = 0, fills = 0, closedTrades = 0;
    std::uint64_t wins = 0, losses = 0, warmupBlocks = 0;
    double winningPnl = 0, losingPnl = 0, tradePnl = 0;
    Epoch lastEquityTime = -1;
    double lastEquity = std::numeric_limits<double>::quiet_NaN();

    Symbol& get(const std::string& name) {
        auto it = symbols.find(name);
        if (it == symbols.end()) {
            auto id = static_cast<int>(std::find(Universe.begin(), Universe.end(), name) - Universe.begin());
            it = symbols.emplace(name, std::make_unique<Symbol>(name, id)).first;
        }
        return *it->second;
    }
    template<class F> void inLaunchOrder(F f) {
        for (const auto& name : Universe) if (symbols.contains(name)) f(*symbols.at(name));
    }
    double portfolioEquity() const {
        double value = cash;
        for (const auto& [_, s] : symbols)
            value += (s->position.side == "BUY" ? 1 : -1) * s->position.quantity * s->mark;
        return value;
    }
    double grossExposure() const {
        double gross = 0;
        for (const auto& [_, s] : symbols) gross += s->position.quantity * s->mark;
        return gross;
    }
    double unrealizedPnl() const {
        double value = 0;
        for (const auto& [_, s] : symbols)
            value += (s->position.side == "BUY" ? 1 : -1) * s->position.quantity * (s->mark - s->position.price);
        return value;
    }
    void equity(Epoch t, bool force = false) {
        const double value = portfolioEquity();
        peak = (std::max)(peak, value);
        maxDrawdown = (std::max)(maxDrawdown, peak - value);
        if (peak > 0) maxDrawdownPct = (std::max)(maxDrawdownPct, (peak - value) / peak * 100);
        if (!force && lastEquity == value && lastEquityTime == t) return;
        equityFile << t << ',' << value << ',' << cash << ',' << grossExposure() << ',' << realized << ','
                   << unrealizedPnl() << ',' << fees << ',' << slip + spread << '\n';
        lastEquity = value; lastEquityTime = t;
    }
    void audit(Epoch t, const Symbol& s, const Pending& p, const std::string& status,
               const std::string& reason, double price = 0, double commission = 0) {
        orders << p.id << ',' << t << ',' << s.name << ',' << p.side << ',' << p.quantity << ','
               << (p.exit ? "EXIT" : "ENTRY") << ',' << status << ',' << reason << ',' << p.submitted << ','
               << p.signalPrice << ',' << price << ',' << commission << ',' << producerCash << '\n';
    }
    void refuse(Epoch t, Symbol& s, const Pending& p, const std::string& reason) {
        ++rejected; audit(t, s, p, "REJECTED", reason);
    }
    void nextGroup() {
        upcoming.clear();
        if (!lookahead) return;
        if (lookahead->kind != "realtime5s") throw std::runtime_error("History after realtime is not permitted");
        Epoch end = lookahead->end;
        while (lookahead && lookahead->end == end) {
            if (lookahead->kind != "realtime5s" || lookahead->start < o.start || lookahead->end > o.end)
                throw std::runtime_error("Realtime data outside requested interval or historical row after warmup");
            if (!symbols.contains(lookahead->symbol)) throw std::runtime_error("Realtime symbol lacks warmup: " + lookahead->symbol);
            upcoming.push_back(*lookahead);
            lookahead = input.read();
        }
    }
    void initialize() {
        lookahead = input.read();
        while (lookahead && lookahead->kind != "realtime5s") {
            const auto& r = *lookahead;
            if (r.end > o.start) throw std::runtime_error("Historical seed bars must be completed by --start");
            auto& s = get(r.symbol);
            auto& bars = r.kind == "history1d" ? s.daily : s.five;
            const sys_days d = nyDate(r.start);
            if (r.kind == "history1d" && !bars.empty() && bars.back().date == d)
                throw std::runtime_error("Duplicate daily session for " + r.symbol);
            bars.push_back({r.start, d, r.asBar()});
            lookahead = input.read();
        }
        if (symbols.empty() || !lookahead) throw std::runtime_error("Input needs both historical warmup and actual replay bars");
        if (!o.synthetic && symbols.size() != Universe.size()) throw std::runtime_error("Actual replay requires all ten production symbols");
        for (const auto& [name, s] : symbols) {
            if (s->daily.size() < 90 || s->five.size() < 200)
                throw std::runtime_error("Insufficient warmup for " + name + ": need >=90 daily and >=200 five-minute bars");
            if (s->daily.front().date > sixMonthsBefore(nyDate(o.start)) + days{7})
                throw std::runtime_error("Daily warmup does not span six calendar months for " + name);
            if (nyDate(o.start) - s->daily.back().date > days{7} || nyDate(o.start) - s->five.back().date > days{7})
                throw std::runtime_error("Stale historical warmup for " + name);
        }
        nextGroup();
        std::filesystem::create_directories(o.out);
        trades.open(std::filesystem::path(o.out) / "trades.csv");
        equityFile.open(std::filesystem::path(o.out) / "equity.csv");
        orders.open(std::filesystem::path(o.out) / "orders.csv");
        if (!trades || !equityFile || !orders) throw std::runtime_error("Cannot create output files");
        trades << std::setprecision(17);
        equityFile << std::setprecision(17);
        orders << std::setprecision(17);
        trades << "symbol,side,entry_timestamp,entry_price,exit_timestamp,exit_price,quantity,entry_reason,exit_reason,gross_pnl,commissions,slippage_cost,spread_cost,net_pnl,duration_seconds\n";
        equityFile << "timestamp,equity,cash,gross_exposure,realized_pnl,unrealized_pnl,commissions,execution_costs\n";
        orders << "order_id,timestamp,symbol,side,quantity,purpose,status,reason,submitted_timestamp,signal_price,fill_price,commission,producer_cash\n";
        refresh(o.start);
        equity(o.start, true);
    }

    static void aggregate(std::deque<TimedBar>& bars, const Row& r, Epoch bucket, sys_days date) {
        if (bars.empty() || bars.back().start != bucket) {
            Bar b = r.asBar(); b.time = std::to_string(bucket);
            bars.push_back({bucket, date, b});
        } else {
            auto& b = bars.back().bar;
            b.high = (std::max)(b.high, r.high); b.low = (std::min)(b.low, r.low); b.close = r.close;
            b.volume = DecimalFunctions::doubleToDecimal(DecimalFunctions::decimalToDouble(b.volume) + r.volume);
        }
    }
    void complete(const Row& r) {
        auto& s = get(r.symbol);
        if (s.lastComplete && r.start > s.lastComplete) ++s.gaps;
        if (!s.firstRealtime) s.firstRealtime = r.start;
        ++s.realtimeRows;
        s.mark = r.close; s.priorVolume = r.volume; s.lastComplete = r.end;
        s.realtime.assign(1, r.asBar());
        if (!r.rth) return;
        sys_days date = nyDate(r.start);
        aggregate(s.five, r, r.start / 300 * 300, date);
        // Daily bucket uses New York civil date, not UTC date. The timestamp is
        // opaque to production DataFetcher; it is never used for session logic.
        const Epoch dailyBucket = date.time_since_epoch().count() * 86400;
        // Historical daily start is exchange open; match same date if present.
        Epoch key = !s.daily.empty() && s.daily.back().date == date ? s.daily.back().start : dailyBucket;
        aggregate(s.daily, r, key, date);
    }
    void refresh(Epoch t) {
        inLaunchOrder([&](Symbol& s) {
            auto earliest = sixMonthsBefore(nyDate(t));
            while (!s.daily.empty() && s.daily.front().date < earliest) s.daily.pop_front();
            std::set<sys_days> dates;
            for (auto it = s.five.rbegin(); it != s.five.rend(); ++it) {
                dates.insert(it->date);
                if (dates.size() > 4) { dates.erase(it->date); break; }
            }
            if (!dates.empty()) while (!s.five.empty() && s.five.front().date < *dates.begin()) s.five.pop_front();
            s.dailySnapshot.clear(); s.fiveSnapshot.clear();
            for (const auto& b : s.daily) s.dailySnapshot.push_back(b.bar);
            for (const auto& b : s.five) s.fiveSnapshot.push_back(b.bar);
        });
    }

    void fill(Epoch t, Symbol& s, const Row& opening) {
        // Only information observable at this open is used: current open price
        // and the PRIOR completed bar's volume. Current OHLCV remains hidden.
        double available = std::floor(s.priorVolume * o.maxParticipation);
        while (!s.pending.empty() && s.pending.front().submitted < t) {
            Pending p = s.pending.front(); s.pending.pop_front();
            if (s.lastComplete == 0 || available < p.quantity) {
                refuse(t, s, p, "prior_observed_volume_cap"); continue;
            }
            if (!p.exit && s.position.quantity != 0) { refuse(t, s, p, "position_already_open"); continue; }
            // The source's exit order is not reduce-only. If its entry was
            // rejected, the opposite market order can open an orphan position.
            const bool closesPosition = p.exit && s.position.quantity != 0;
            const double commission = (std::max)(o.minimumCommission, p.quantity * o.commission);
            const double slippage = p.quantity * opening.open * o.slippageBps / 10000;
            const double spreadCost = p.quantity * opening.open * o.halfSpreadBps / 10000;
            const int direction = p.side == "BUY" ? 1 : -1;
            const double price = opening.open * (1 + direction * (o.slippageBps + o.halfSpreadBps) / 10000);
            // All symbols at this timestamp have already been marked at their
            // newly observed opens before applying the shared funding controls.
            const double afterCosts = portfolioEquity() - commission - slippage - spreadCost;
            const double allowed = (std::min)({10500.0, o.capital * o.leverage, afterCosts * o.leverage});
            if (!closesPosition && (afterCosts <= 0 || grossExposure() + p.quantity * opening.open > allowed + 1e-9)) {
                refuse(t, s, p, "portfolio_buying_power"); continue;
            }
            available -= p.quantity;
            cash -= direction * p.quantity * price + commission;
            fees += commission; slip += slippage; spread += spreadCost; ++fills;
            if (!closesPosition) {
                s.position = {p.quantity, p.side, t, price, commission, slippage, spreadCost,
                    p.exit ? "orphan_exit_after_rejected_entry" : "production_analyzeData"};
            } else {
                const auto pos = s.position;
                const double gross = (pos.side == "BUY" ? 1 : -1) * pos.quantity * (price - pos.price);
                const double allFees = pos.fees + commission;
                const double net = gross - allFees;
                realized += gross; tradePnl += net; ++closedTrades;
                if (net > 0) { ++wins; winningPnl += net; }
                if (net < 0) { ++losses; losingPnl += net; }
                trades << s.name << ',' << pos.side << ',' << pos.entry << ',' << pos.price << ',' << t << ',' << price << ','
                       << pos.quantity << ',' << pos.entryReason << ",SMA10_cross," << gross << ',' << allFees << ','
                       << pos.slippage + slippage << ',' << pos.spread + spreadCost << ',' << net << ',' << t - pos.entry << '\n';
                s.position = {};
            }
            audit(t, s, p, "FILLED", p.exit && !closesPosition ? "orphan_exit_after_rejected_entry" : "next_strictly_later_5s_open", price, commission);
            equity(t);
        }
    }
    void evaluate(Epoch t) {
        QuietProduction quiet;
        inLaunchOrder([&](Symbol& s) {
            if (s.terminated || s.realtime.empty()) return;
            if (s.dailySnapshot.size() < 15 || s.fiveSnapshot.size() < 200) {
                ++warmupBlocks;
                s.terminated = true; // The production worker returns on missing history.
                return;
            }
            ++calls;
            OrderInstructions instructions{};
            bool entrySignal = bt::signal(instructions, *s.fetcher, s.dailySnapshot, s.fiveSnapshot, s.realtime, t);
            if (entrySignal) {
                ++signals;
                if (!s.entrySubmitted && !s.exitSubmitted) {
                    int qty = bt::quantity(*s.fetcher, s.fiveSnapshot, s.realtime.back().close, instructions.action);
                    Pending p{t, nextOrder++, qty, instructions.action, false, s.realtime.back().close};
                    double nominal = qty * p.signalPrice;
                    if (qty <= 0 || nominal > 10500 || nominal > producerCash) {
                        refuse(t, s, p, "production_invalid_quantity_or_cash");
                        s.terminated = true; return;
                    }
                    // atomic<int>::operator-=(double) converts the RHS to int.
                    producerCash -= static_cast<int>(nominal);
                    s.entrySubmitted = true; s.intendedSide = p.side; s.intendedQuantity = qty;
                    s.pending.push_back(p); audit(t, s, p, "SUBMITTED", "production_analyzeData");
                }
            }
            if (s.entrySubmitted && !s.exitSubmitted &&
                bt::exitSignal(s.intendedSide, s.realtime.back().close, s.fetcher->getSma10(s.fiveSnapshot))) {
                Pending p{t, nextOrder++, s.intendedQuantity, s.intendedSide == "BUY" ? "SELL" : "BUY", true, s.realtime.back().close};
                s.pending.push_back(p); s.exitSubmitted = true;
                audit(t, s, p, "SUBMITTED", "SMA10_cross");
            }
        });
    }

    void summary() {
        std::ofstream out(std::filesystem::path(o.out) / "summary.json");
        out << std::setprecision(17);
        std::size_t open = 0, terminated = 0, pending = 0;
        for (const auto& [_, s] : symbols) { open += s->position.quantity != 0; terminated += s->terminated; pending += s->pending.size(); }
        out << "{\n  \"status\": \"" << (o.synthetic ? "synthetic_test_only" : "completed_replay") << "\",\n"
            << "  \"synthetic_data\": " << (o.synthetic ? "true" : "false") << ",\n"
            << "  \"start_epoch\": " << o.start << ",\n  \"end_epoch\": " << o.end << ",\n"
            << "  \"initial_capital\": " << o.capital << ",\n  \"final_equity\": " << portfolioEquity() << ",\n"
            << "  \"net_pnl\": " << portfolioEquity() - o.capital << ",\n"
            << "  \"net_return_pct\": " << (portfolioEquity() / o.capital - 1) * 100 << ",\n"
            << "  \"closed_trades\": " << closedTrades << ",\n  \"winning_trades\": " << wins << ",\n  \"losing_trades\": " << losses << ",\n"
            << "  \"win_rate_pct\": " << (closedTrades ? 100.0 * wins / closedTrades : 0) << ",\n"
            << "  \"average_winning_trade\": " << (wins ? winningPnl / wins : 0) << ",\n"
            << "  \"average_losing_trade\": " << (losses ? losingPnl / losses : 0) << ",\n"
            << "  \"average_trade_pnl\": " << (closedTrades ? tradePnl / closedTrades : 0) << ",\n"
            << "  \"expectancy_per_trade\": " << (closedTrades ? tradePnl / closedTrades : 0) << ",\n"
            << "  \"profit_factor\": ";
        if (losingPnl < 0) out << winningPnl / -losingPnl; else out << "null";
        out << ",\n  \"max_drawdown_usd\": " << maxDrawdown << ",\n  \"max_drawdown_pct\": " << maxDrawdownPct << ",\n"
            << "  \"realized_gross_pnl\": " << realized << ",\n  \"unrealized_gross_pnl\": " << unrealizedPnl() << ",\n"
            << "  \"commissions\": " << fees << ",\n  \"slippage_cost\": " << slip << ",\n  \"spread_cost\": " << spread << ",\n"
            << "  \"execution_costs\": " << slip + spread << ",\n  \"producer_cash_remaining\": " << producerCash << ",\n"
            << "  \"strategy_calls\": " << calls << ",\n  \"true_signal_calls\": " << signals << ",\n"
            << "  \"warmup_blocked_evaluations\": " << warmupBlocks << ",\n  \"rejected_orders\": " << rejected << ",\n"
            << "  \"filled_orders\": " << fills << ",\n  \"open_positions\": " << open << ",\n"
            << "  \"terminated_symbols\": " << terminated << ",\n  \"unfilled_orders_at_end\": " << pending << ",\n"
            << "  \"leverage\": " << o.leverage << ",\n  \"commission_per_share\": " << o.commission << ",\n"
            << "  \"minimum_commission\": " << o.minimumCommission << ",\n  \"slippage_bps\": " << o.slippageBps << ",\n"
            << "  \"half_spread_bps\": " << o.halfSpreadBps << ",\n  \"max_participation\": " << o.maxParticipation << ",\n"
            << "  \"source_exit_policy\": \"SMA10 only; no stop-loss or break-even found in supplied sources\",\n"
            << "  \"liquidity_policy\": \"full fills capped by prior observed five-second volume; no future volume inspected\",\n"
            << "  \"history_policy\": \"RTH daily and five-minute aggregates from observed realtime bars; frozen at five-minute boundary plus nine seconds\",\n"
            << "  \"coverage\": [\n";
        bool first = true;
        for (const auto& name : Universe) if (symbols.contains(name)) {
            const auto& s = *symbols.at(name);
            if (!first) out << ",\n"; first = false;
            out << "    {\"symbol\":\"" << name << "\",\"rows\":" << s.realtimeRows
                << ",\"first_epoch\":" << s.firstRealtime << ",\"last_epoch\":" << s.lastComplete
                << ",\"observed_gaps\":" << s.gaps << ",\"open_quantity\":" << s.position.quantity
                << ",\"open_side\":\"" << s.position.side << "\",\"open_entry_reason\":\"" << s.position.entryReason
                << "\",\"mark\":" << s.mark << '}';
        }
        out << "\n  ]\n}\n";
        if (!out) throw std::runtime_error("Writing summary failed");
    }

public:
    explicit Replay(Options opts) : o(std::move(opts)), input(o.data), cash(o.capital), peak(o.capital) {}
    void run() {
        initialize();
        Epoch nextEval = o.start;
        Epoch nextRefresh = o.start / 300 * 300 + 309;
        while (true) {
            Epoch openAt = upcoming.empty() ? Never : upcoming.front().start;
            Epoch closeAt = active.empty() ? Never : active.front().end;
            Epoch t = (std::min)({nextEval, nextRefresh, openAt, closeAt, o.end});
            // Market completions precede pending fills; strategy sees newly
            // completed bars only after this point. Simultaneous signals use the
            // production launch order, never nondeterministic OS scheduling.
            if (t == closeAt) {
                for (const auto& r : active) complete(r);
                active.clear(); equity(t);
            }
            if (t == o.end) break;
            if (t == openAt) {
                for (const auto& r : upcoming) get(r.symbol).mark = r.open;
                equity(t);
                inLaunchOrder([&](Symbol& s) {
                    auto r = std::find_if(upcoming.begin(), upcoming.end(), [&](const Row& b) { return b.symbol == s.name; });
                    if (r != upcoming.end()) fill(t, s, *r);
                });
                active = std::move(upcoming);
                nextGroup();
            }
            if (t == nextRefresh) { refresh(t); nextRefresh += 300; nextEval = t; }
            if (t == nextEval) { evaluate(t); nextEval += 2; }
        }
        inLaunchOrder([&](Symbol& s) {
            if (!o.synthetic && s.realtimeRows == 0)
                throw std::runtime_error("No replay observations for production symbol " + s.name);
            for (const auto& p : s.pending) audit(o.end, s, p, "UNFILLED", "end_of_available_replay");
        });
        equity(o.end, true);
        if (!trades || !equityFile || !orders) throw std::runtime_error("Writing CSV outputs failed");
        summary();
        std::cout << (o.synthetic ? "Synthetic verification" : "Historical replay") << " complete: "
                  << closedTrades << " closed trades; " << portfolioEquity() << " final equity.\n";
    }
};
} // namespace

int main(int argc, char** argv) {
    try { Replay(options(argc, argv)).run(); return 0; }
    catch (const std::exception& e) { std::cerr << "Backtest failed: " << e.what() << '\n'; return 1; }
}
