#pragma once
#include "bar.h"
#include <vector>
#include "Contract.h"
#include "OrderInstructions.h"
#include <chrono>
#include <iostream>

class DataFetcher
{
private:
	std::vector<Bar>* barsPtr=nullptr;
	Contract contract;
	int reqid;
	double sma200;
	double sma20;
	double yesterdayClose;
	double lastPrice = 0;
	bool valid = false;
	////////////////////IbApi _api;

public:
	DataFetcher(int reqid, std::vector<Bar>* barsPtr, Contract contract) : reqid(reqid), barsPtr(barsPtr), contract(contract) {}
	
	
	Contract& getContract() { return contract; }
	//double getSma200(const IbApi& api) {};
	double getSma20(const std::vector<Bar>& bars);
	double getSma200(const std::vector<Bar>& bars);
	double getSma10(const std::vector<Bar>& bars);
	double getYesterdayClose(const std::vector<Bar>& bars);
	double lastUpdatePrice(const std::vector<Bar>& bars);
	double getAtr(const std::vector<Bar>& bars);
	double getVolume();
	bool validBuyInTime();
	bool getVwapTrend();
	double getCandleLow(const std::vector<Bar>& bars);
	double getCandleHigh(const std::vector<Bar>& bars);
	double todayOpenPrice(const std::vector<Bar>& bars);
	std::pair<std::string, double> validBar(const std::vector<Bar>& bars);
	bool priceOptmization(double rightNowPrice);
	bool min2Candle();
	bool min5Candle();
	bool trendCheck();
	std::string QQQtrendCheck();
	std::string GapCheck(double yesterdayClose,double rightNowPrice);
	double getRisk() { return 50; };
	double getStopLoss();
	double getQuantity();
	std::pair<int, int> dailySMA20_200Cross();
	// QQQ specific methods
	std::pair<int, int> dailySMA20_200QQQ();
};

