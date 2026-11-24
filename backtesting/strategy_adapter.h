#pragma once

// These are the existing strategy's types, compiled without source changes.
#include "../traderBot/DataFetcher.h"
#include "../traderBot/OrderInstructions.h"
#include <cstdint>
#include <string>
#include <vector>

namespace bt {
// daily/five contain only observations available at the evaluation time.
// The DataFetcher must reference the supplied realtime vector.
bool signal(OrderInstructions& instructions, DataFetcher& fetcher,
            const std::vector<Bar>& daily, const std::vector<Bar>& five,
            const std::vector<Bar>& realtime, std::int64_t evaluation_epoch);
// Returns zero for undefined/nonfinite/out-of-range sizing inputs.
int quantity(DataFetcher& fetcher, const std::vector<Bar>& five,
             double lastPrice, const std::string& action);
bool exitSignal(const std::string& side, double price, double sma10);
bool validTime(std::int64_t epoch);
}
