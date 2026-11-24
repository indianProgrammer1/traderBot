#define NOMINMAX
#include "DataFetcher.h"


std::pair<std::string, double> DataFetcher::validBar(const std::vector<Bar>& bars) {
	if (bars.size() < 2) {
		return { "barsEmpty.",0 };
	}
	const Bar& lastBar = bars[bars.size() - 2];
	std::cout 
			<< "\nTime: " << lastBar.time
			<< ", High: " << lastBar.high
			<< ", Low: " << lastBar.low
			<< ", Open: " << lastBar.open
			<< ", Close: " << lastBar.close
			<< std::endl;

	double barRange = lastBar.high - lastBar.low;
	double barBody = std::abs(lastBar.close - lastBar.open);
	bool vaild = (barBody >= 0.7 * barRange) /* && (barBody >= 0.0035 * lastBar.close) && (barBody <= 0.007 * lastBar.close) */;
	if(vaild && lastBar.close > lastBar.open || lastBar.high == lastBar.close) {
		return { "GreenBar", std::abs(lastBar.high - lastBar.low) };
	}
	else if(vaild && lastBar.close < lastBar.open || lastBar.low == lastBar.close) {
		return { "RedBar",std::abs(lastBar.high - lastBar.low) };
	}
	else {
		return {"false",0 };
	}

}
bool DataFetcher::validBuyInTime() {
	using namespace std::chrono;

	static const time_zone* israelZone =
		locate_zone("Asia/Jerusalem");

	const zoned_time israelTime{
		israelZone,
		system_clock::now()
	};

	const auto localNow = israelTime.get_local_time();
	const auto today = floor<days>(localNow);
	const auto timeOfDay = localNow - today;

	return timeOfDay >= hours{ 16 } + minutes{ 35 } + seconds{10} &&
		timeOfDay < hours{ 17 } + minutes{ 01 };
	return true;
}
bool DataFetcher::priceOptmization(double rightNowPrice) {
	if(static_cast<int>(rightNowPrice) % 10 < 3 ) {
		return true;
	}
	return false;
}
double DataFetcher::todayOpenPrice(const std::vector<Bar>& bars) {
	if (bars.empty()) {
		return 0.0;
	}
	return bars[bars.size() - 1].open;
}
double DataFetcher::getAtr(const std::vector<Bar>& bars) {

	constexpr std::size_t period = 14;

	// צריך 15 נרות כדי לחשב לפחות 14 ערכי TR
	if (bars.size() < period + 1) {
		return 0.0;
	}

	std::vector<double> trueRanges;
	trueRanges.reserve(bars.size() - 1);

	for (std::size_t i = 1; i < bars.size(); ++i) {
		const double previousClose = bars[i - 1].close;

		const double tr =
			std::max(bars[i].high, previousClose) -
			std::min(bars[i].low, previousClose);

		trueRanges.push_back(tr);
	}

	// ערך התחלתי: ממוצע פשוט של 14 ערכי TR
	double atr = 0.0;

	for (std::size_t i = 0; i < period; ++i) {
		atr += trueRanges[i];
	}

	atr /= static_cast<double>(period);

	// Finviz מגדיר את המדד כ־EMA(14)
	constexpr double alpha = 2.0 / (period + 1.0);

	for (std::size_t i = period; i < trueRanges.size(); ++i) {
		atr = alpha * trueRanges[i] + (1.0 - alpha) * atr;
	}

	return atr;
}
double DataFetcher::getSma20(const std::vector<Bar>& bars) {
	constexpr std::size_t period = 20;

	if (bars.size() < period) {
		return 0.0;
	}

	double sum = 0.0;
	const std::size_t firstBar = bars.size() - period;

	for (std::size_t i = firstBar; i < bars.size(); ++i) {
		sum += bars[i].close;
	}

	return sum / static_cast<double>(period);
	
}
double DataFetcher::getSma10(const std::vector<Bar>& bars) {
	constexpr std::size_t period = 10;

	if (bars.size() < period) {
		return 0.0;
	}

	double sum = 0.0;
	const std::size_t firstBar = bars.size() - period;

	for (std::size_t i = firstBar; i < bars.size(); ++i) {
		sum += bars[i].close;
	}

	return sum / static_cast<double>(period);

}
double DataFetcher::getSma200(const std::vector<Bar>& bars) {

	constexpr std::size_t period = 200;

	if (bars.size() < period) {
		return 0.0;
	}

	double sum = 0.0;
	const std::size_t firstBar = bars.size() - period;

	for (std::size_t i = firstBar; i < bars.size(); ++i) {
		sum += bars[i].close;
	}

	return sum / static_cast<double>(period);



}
double DataFetcher::getYesterdayClose(const std::vector<Bar>& bars) {
	if (bars.size() < 2) {
		return 0.0;
	}
	return bars[bars.size() - 2].close;
}
double DataFetcher::lastUpdatePrice(const std::vector<Bar>& bars) {
	if (bars.empty()) {
		return 0.0;
	}
	return bars.back().close;
}
double DataFetcher::getVolume() {
	if (barsPtr == nullptr || barsPtr->empty()) {
		return 0.0;
	}
	const Bar& lastBar = barsPtr->back();
	return DecimalFunctions::decimalToDouble(lastBar.volume);
}
double DataFetcher::getCandleLow(const std::vector<Bar>& bars) {

	if (bars.size() < 2) {
		return 400.0;
	}
	const Bar& lastBar = bars[bars.size() - 2];
	std::cout
		<< "\nTime: " << lastBar.time
		<< ", High: " << lastBar.high
		<< ", Low: " << lastBar.low
		<< ", Open: " << lastBar.open
		<< ", Close: " << lastBar.close
		<< std::endl;
	
	return lastBar.low;
}
double DataFetcher::getCandleHigh(const std::vector<Bar>& bars) {
	if (bars.size() < 2) {
		return 0.0;
	}
	const Bar& lastBar = bars[bars.size() - 2];
	std::cout
		<< "\nTime: " << lastBar.time
		<< ", High: " << lastBar.high
		<< ", Low: " << lastBar.low
		<< ", Open: " << lastBar.open
		<< ", Close: " << lastBar.close
		<< std::endl;
	return lastBar.high;
}

std::string DataFetcher::GapCheck(double yesterdayClose,double rightNowPrice) {

//	std::cout << "\nRight Now Price: " << rightNowPrice << std::endl;
//	std::cout << "Yesterday Close: " << yesterdayClose << std::endl;
	if ( rightNowPrice /yesterdayClose > 1.03
		|| rightNowPrice /yesterdayClose < 0.97) {
		return "TooMuchGAPMotherFucker";
	}
	else 
		return "OkGap.";
	
	
}
std::string DataFetcher::QQQtrendCheck() {
	//need to implement the logic for QQQ trend check
	return "QQQ trend check not implemented yet.";
}








