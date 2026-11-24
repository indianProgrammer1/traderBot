#include "IbApi.h"



void IbApi::error(int id, time_t errorTime, int errorCode, const std::string& errorString, const std::string& advancedOrderRejectJson) {
	std::cerr << "Error ID: " << id
		<< " | Time: " << errorTime
		<< " | Code: " << errorCode
		<< " | Message: " << errorString << std::endl;
}
void IbApi::tickPrice(TickerId tickerId, TickType field, double price, const TickAttrib& attrib) {
	// Interested in BID and ASK 
	marketData[tickerId].push_back(price);

	std::cout << "Tick Price -> ID: " << tickerId
		<< ", Field: " << field
		<< ", Price: " << price << std::endl;
}
void IbApi::historicalDataUpdate(TickerId reqId, const Bar& bar) {
	marketData[reqId].push_back(bar.close);
	std::cout << "Live 5-Sec Bar [" << reqId << "]: "
		<< "Close Price: " << bar.close
		<< ", Volume: " << bar.volume << std::endl;
}
void IbApi::sendMarketData(int tickerId, std::vector<double>& target) {
	if (marketData[tickerId].size())
	{
		target.insert(
			target.end(),
			marketData[tickerId].begin(),
			marketData[tickerId].end());
	}
}
void IbApi::historicalData(TickerId reqId, const Bar& bar) {
	{
		std::lock_guard <std::mutex> lock(barsMutex);
		barsByReqId[reqId].push_back(bar);
	}
	
	marketData[reqId].push_back(bar.close);
	//std::cout << "Historical bar [" << reqId << "] "
	//	<< "Time: " << bar.time
	//	<< ", High: " << bar.high
	//	<< ", Low: " << bar.low
	//	<< ", Open: " << bar.open
	//	<< ", Close: " << bar.close
	//	<< std::endl;
}
void IbApi::realtimeBar(TickerId reqId, long time, double open, double high,double low, double close, Decimal volume,Decimal wap, int count) {
	// המרת ה-Timestamp (שניות מאז Epoc) לפורמט שעה קריא
	std::time_t barTime = static_cast<std::time_t>(time);
	char timeBuffer[80];
	std::strftime(timeBuffer, sizeof(timeBuffer), "%H:%M:%S", std::localtime(&barTime));
	{
		std::lock_guard <std::mutex> lock(barsMutex);
		barsByReqId[reqId].push_back(Bar{ timeBuffer, high, low, open, close, wap });
	}
	historicalCv.notify_all();

//std::cout << "[" << timeBuffer << "] [Symbol: " << symbolByReqId[reqId] << "]"
//	<< "  Open:  " << open
//	<< "  High:  " << high
//	<< "  Low:   " << low
//	<< "  Close: " << close << "\n"
//	<< "----------------------------------------" << std::endl;


}

int IbApi::getYesderdayClose(std::string symbol) {
	Contract contract;
	contract.symbol = symbol;
	contract.secType = "STK";
	contract.currency = "USD";
	contract.exchange = "SMART";
	int reqId = ++idCounter;
	client->reqHistoricalData(
		reqId,
		contract,
		"",
		"1 W",
		"1 day",
		"TRADES",
		1,
		1,
		false,
		TagValueListSPtr()
	);
	return reqId;



}
int IbApi::getATRbars(std::string symbol) {
	Contract contract;
	contract.symbol = symbol;
	contract.secType = "STK";
	contract.currency = "USD";
	contract.exchange = "SMART";
	int reqId = ++idCounter;

	client->reqHistoricalData(
		reqId,
		contract,
		"",
		"6 M",
		"1 day",
		"TRADES",
		1,
		1,
		false,
		TagValueListSPtr()
	);
	return reqId;
}
int IbApi::getSma20bars(std::string symbol) {
	Contract contract;
	contract.symbol = symbol;
	contract.secType = "STK";
	contract.currency = "USD";
	contract.exchange = "SMART";
	int reqId = ++idCounter;
	client->reqHistoricalData(
		reqId,
		contract,
		"",
		"2 D",
		"5 mins",
		"TRADES",
		1,
		1,
		false,
		TagValueListSPtr()
	);
	return reqId;
}
int IbApi::getSma200bars(std::string symbol) {
	Contract contract;
	contract.symbol = symbol;
	contract.secType = "STK";
	contract.currency = "USD";
	contract.exchange = "SMART";
	int reqId = ++idCounter;
	client->reqHistoricalData(
		reqId,
		contract,
		"",
		"4 D",
		"5 mins",
		"TRADES",
		1,
		1,
		false,
		TagValueListSPtr()
	);
	return reqId;

}
int IbApi::getLastPrice(std::string symbol) {

	Contract contract;
	contract.symbol = symbol;
	contract.secType = "STK";
	contract.currency = "USD";
	contract.exchange = "SMART";
	int reqId = ++idCounter;

	client->reqMktData(
		reqId,
		contract,
		"",
		true,                   // snapshot חד־פעמי
		true,                  // לא regulatory snapshot בתשלום
		TagValueListSPtr()
	);
	return reqId;
}



void IbApi::historicalDataEnd(
	int reqId,
	const std::string& start,
	const std::string& end)
{
	{
		std::lock_guard<std::mutex> lock(barsMutex);
		completedRequests.insert(reqId);
	}

	historicalCv.notify_all();
}