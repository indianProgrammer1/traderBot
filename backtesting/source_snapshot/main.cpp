#include "IbApi.h"
#include <thread>
#include <mutex>
#include <Decimal.h>
#include "DataFetcher.h"
#include <atomic>
#include "OrderInstructions.h"
#include "SignalEngine.h"

const char* RED = "\033[31m";
const char* GREEN = "\033[32m";
const char* YELLOW = "\033[33m";
const char* RESET = "\033[0m";

bool analyzeData(OrderInstructions& instructions,
	const std::string& symbol,
	double atr,
	double sma10,
	double sma20,
	double sma200,
	double lastPrice,
	bool vaildtime,
	double yesterdayClose,
	std::string vaildCandle,
	double volume,
	double todayOpenPrice,
	const std::string& gapCheck,
	const std::string& QQQtrendCheck,
	bool priceOptmization);



int main() {

	// Create an instance of IbApi
	std::atomic<bool> orderExcecuted = false;
	std::atomic <int> vaildCashBalance = 4200 * 2.5;
	EReaderOSSignal signal;
	IbApi apiData;
	EClientSocket client(&apiData, &signal);
	apiData.setClient(&client);
	std::unordered_map < std::string,std::pair< int, std::string>> positions;


	// Connect to the TWS or IB Gateway
	if (client.eConnect("127.0.0.1", 7497, 0)) {
		std::cout << "Connected!" << std::endl;
		EReader reader(&client, &signal);
		reader.start();
		std::thread msgThread([&]() {
			while (client.isConnected()) {
				signal.waitForSignal();
				reader.processMsgs();
			}
			});

		// Wait until we have a valid order ID
		auto launchThread = [&](std::string symbol) {
			const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
			while (!apiData.hasValidOrderId()) {
				if (!client.isConnected() ||  
					std::chrono::steady_clock::now() >= deadline) {
					std::cerr << "IBKR order ID was not received\n";
					return; // Exit this symbol's worker.
				}
				std::this_thread::sleep_for(std::chrono::milliseconds(100));
			}


			//requestHistoricalOnceAday + 
			Contract Contract1;
			TickerId reqId = apiData.getNextRequestId(); // getIDfromtheclass
			Contract1.symbol = symbol;
			Contract1.secType = "STK";
			Contract1.currency = "USD";
			Contract1.exchange = "SMART";
			apiData.registerSymbol(reqId, Contract1.symbol);
			client.reqRealTimeBars(reqId, Contract1, 5, "TRADES", false, TagValueListSPtr());
			DataFetcher fetcher(reqId, apiData.getptrbar(reqId), Contract1);


			//requestHistoricalEvery5minutes 
			using Clock = std::chrono::system_clock;
			using FiveMinutes = std::chrono::duration<long long, std::ratio<300>>;

			std::atomic <bool> openOrderExecuted = false;
			std::atomic <bool> closeOrderExecuted = false;


			while (client.isConnected() && !orderExcecuted.load()) {
				std::unique_lock<std::mutex> barsLock(apiData.barsMutex);

				const Clock::time_point nextRefresh = std::chrono::floor<FiveMinutes>(Clock::now()) + FiveMinutes{ 1 } + std::chrono::seconds{ 9 };
				std::cout << "\n" << symbol << " refresh at " << std::chrono::zoned_time{ std::chrono::current_zone(), std::chrono::floor<std::chrono::seconds>(Clock::now()) } << std::endl;
				//may i can reduce the requets because there is same data.
				TickerId atrid = apiData.getATRbars(symbol);
				TickerId yesterdayCloseId = apiData.getYesderdayClose(symbol); //getIDfromTHEIapiItself 
				TickerId sma200id = apiData.getSma200bars(symbol);
				TickerId sma20id = apiData.getSma20bars(symbol);
				std::cout << "smaid20: " << sma20id << " sma200id: " << sma200id << std::endl;




				//Addition
				const bool received = apiData.historicalCv.wait_until(
					barsLock,
					(std::min)(nextRefresh, Clock::now() + std::chrono::seconds(7)),
					[&]() {
						const bool historicalDataReceived =
							apiData.completedRequests.count(atrid) > 0 &&
							apiData.completedRequests.count(sma20id) > 0 &&
							apiData.completedRequests.count(sma200id) > 0 &&
							apiData.completedRequests.count(yesterdayCloseId) > 0;

						const auto amd = apiData.barsByReqId.find(reqId);
						const bool amdReceived = amd != apiData.barsByReqId.end() && !amd->second.empty();

						return historicalDataReceived && amdReceived;
					}
				);
				const auto& atrbars = apiData.barsByReqId[atrid];
				const auto& sma20bars = apiData.barsByReqId[sma20id];
				const auto& sma10bars = apiData.barsByReqId[sma20id];
				const auto& sma200bars = apiData.barsByReqId[sma200id];
				const auto& yesterdayCloseBars = apiData.barsByReqId[yesterdayCloseId];

				if (!received || atrbars.size() < 15 || sma20bars.size() < 20 || sma200bars.size() < 200 || yesterdayCloseBars.size() < 2)
				{
					std::cout << "Historical data not fully received" << std::endl;
					return;
				}



				barsLock.unlock();

				OrderInstructions instructions; // Create an instance of OrderInstructions
				// Print check to vaild the historical data
				while (client.isConnected() && !orderExcecuted.load() && Clock::now() < nextRefresh) {
					barsLock.lock();

					if (analyzeData(instructions, symbol,
						fetcher.getAtr(atrbars),
						fetcher.getSma10(sma20bars),
						fetcher.getSma20(sma20bars),
						fetcher.getSma200(sma200bars),
						fetcher.lastUpdatePrice(apiData.barsByReqId[reqId]),
						fetcher.validBuyInTime(),
						fetcher.getYesterdayClose(yesterdayCloseBars),
						fetcher.validBar(sma20bars),
						fetcher.getVolume(),
						fetcher.todayOpenPrice(yesterdayCloseBars),
						fetcher.GapCheck(fetcher.getYesterdayClose(yesterdayCloseBars), fetcher.lastUpdatePrice(apiData.barsByReqId[reqId])),
						fetcher.QQQtrendCheck(),
						fetcher.priceOptmization(fetcher.lastUpdatePrice(apiData.barsByReqId[reqId])))) {

						bool expected = false;
						// startTrade
						if (!openOrderExecuted && !closeOrderExecuted) {

							OrderId validOrderId = apiData.getNextOrderId();
							Order order;
							order.orderId = validOrderId;
							order.action = instructions.action;
							order.orderType = "MKT";
							int quantity;
							double candleLow = fetcher.getCandleLow(sma20bars);
							double candleHigh = fetcher.getCandleHigh(sma20bars);
							double risk = fetcher.getRisk();
							double lastPrice = fetcher.lastUpdatePrice(apiData.barsByReqId[reqId]);
							if (instructions.action == "BUY") { quantity = std::floor(std::abs(risk / (lastPrice - candleLow))); }
							else quantity = std::floor(std::abs(risk / (candleHigh - lastPrice)));
							if (lastPrice - candleLow == 0) {
								std::cout << symbol << ":LastPrice - CandleLow is 0, cannot place order." << std::endl;
								orderExcecuted = false;
								return;
							}
							if (quantity == 0 ||
								quantity == INFINITE ||
								quantity * lastPrice > 4200 * 2.5 ||
								vaildCashBalance < quantity * lastPrice) {
								"\n";
								std::cout << symbol << ":Quantity is : " << quantity << " cannot place order." << std::endl;
								orderExcecuted = false;
								return;
							}
							order.totalQuantity = DecimalFunctions::doubleToDecimal(quantity);
							order.cashQty = UNSET_DOUBLE;
							order.account = "DU3384655";
							order.outsideRth = true;
							order.tif = "GTC";
							client.placeOrder(validOrderId, fetcher.getContract(), order);
							vaildCashBalance -= quantity * lastPrice;
							if (instructions.action == "BUY")std::cout << GREEN << "Order executed for " << symbol << " with quantity: " << quantity << " CandleLow: " << candleLow << RESET << std::endl;
							if (instructions.action == "SELL")std::cout << RED << "Order executed for " << symbol << " with quantity: " << quantity << " CandleHigh: " << candleHigh << RESET << std::endl;
							openOrderExecuted = true;
							positions[symbol] = { quantity, instructions.action };
						}
					
					}
						// endTrade
						if (openOrderExecuted && !closeOrderExecuted) {


							double lastPrice = fetcher.lastUpdatePrice(apiData.barsByReqId[reqId]);
							double sma10 = fetcher.getSma10(sma20bars);

							if (lastPrice < sma10 && positions[symbol].second == "BUY" ||
								lastPrice > sma10 && positions[symbol].second == "SELL") {

								OrderId validOrderId = apiData.getNextOrderId();
								Order order;
								order.orderId = validOrderId;
								order.action = positions[symbol].second == "BUY" ? "SELL" : "BUY";
								order.orderType = "MKT";
								order.totalQuantity = DecimalFunctions::doubleToDecimal(positions[symbol].first);
								order.cashQty = UNSET_DOUBLE;
								order.account = "DU3384655";
								order.outsideRth = true;
								order.tif = "GTC";
								client.placeOrder(validOrderId, fetcher.getContract(), order);
								closeOrderExecuted = true;
							}

						
						}
				

					barsLock.unlock();
					std::this_thread::sleep_until((std::min)(nextRefresh, Clock::now() + std::chrono::seconds(2)));
				} // End of analysis loop.



			}

			}; // End of launchThread.






		std::thread thread1(launchThread, "TSLA");
		std::thread	thread2(launchThread, "NFLX");
		std::thread	thread3(launchThread, "CRWD");
		std::thread	thread4(launchThread, "MRNA");
		std::thread thread5(launchThread, "AMD");
		std::thread thread6(launchThread, "NVDA");
		std::thread thread7(launchThread, "AAPL");
		std::thread thread8(launchThread, "ROKU");
		std::thread thread9(launchThread, "PDD");
		std::thread thread10(launchThread,"MSFT");







		thread1.join();
		thread2.join();
		thread3.join();
		thread4.join();
		thread5.join();
		thread6.join();
		thread7.join();
		thread8.join();
		thread9.join();
		thread10.join();




		client.eDisconnect();
		signal.issueSignal();

		if (msgThread.joinable()) {
			msgThread.join();
		}
	}
	else {
		std::cout << "Could not connect!" << std::endl;
	}
}


bool analyzeData(OrderInstructions& instructions, const std::string& symbol,
	double atr,
	double sma10,
	double sma20,
	double sma200,
	double lastPrice,
	bool vaildtime,
	double yesterdayClose,
	std::string vaildCandle,
	double volume,
	double todayOpenPrice,
	const std::string& gapCheck,
	const std::string& QQQtrendCheck,
	bool priceOptmization)
{

	std::cout << "\n" << symbol << " Historical Data Check:" << std::endl;
	std::cout << YELLOW << "1.ATR: " << atr << RESET << std::endl;
	std::cout << "2.SMA20: " << sma20 << std::endl;
	std::cout << "3.SMA200: " << sma200 << std::endl;
	std::cout << GREEN << "4.Last Price: " << lastPrice << RESET << std::endl;
	std::cout << "5.VaildTime: " << (vaildtime ? "True" : "False") << std::endl; // V.
	std::cout << YELLOW << "6.Yesterday Close: " << yesterdayClose << RESET << std::endl;
	std::cout << "7.vaildCandle: " << vaildCandle << std::endl; // V.
	std::cout << "8.vaildVolume: " << volume << std::endl;
	std::cout << YELLOW << "9.todayOpenPrice: " << todayOpenPrice << RESET << std::endl;
	std::cout << "10.GapCheck: " << gapCheck << std::endl;
	std::cout << "11.QQQtrendCheck: " << QQQtrendCheck << std::endl;
	std::cout <<"12.SMA10: " << sma10 << std::endl;
	//std::cout << "12.sexyPriceOptimization:" << (priceOptmization ? "True" : "False") << std::endl;

	if (!vaildtime) return false;
	if (vaildCandle == "false") return false;
	 if (!(std::abs(lastPrice - yesterdayClose) < atr * 0.40)) return false;
	 //long position
	if (sma20 > sma200 && vaildCandle == "GreenBar" && lastPrice > sma20) {
		instructions.action = "BUY";
		return true;
	}
	//short position
	if (sma20 < sma200 && vaildCandle == "RedBar" && lastPrice < sma20) {
		instructions.action = "SELL";
		return true;
	}

	return false;


}
