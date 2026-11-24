#pragma once
#include <string>
#include <iostream>
#include <thread>
#include <chrono>
class SignalEngine
{
private:
	std::string symbol;
    double atr;
    double sma20;
    double sma200;
    double lastPrice;
    bool vaildtime;
    double yesterdayClose;
    bool vaildCandle;
    double volume;
    double todayOpenPrice;
    std::string gapCheck;
    std::string QQQtrendCheck;
    bool priceOptmization;

public:
    SignalEngine(
        const std::string& symbol,
        double atr,
        double sma20,
        double sma200,
        double lastPrice,
        bool vaildtime,
        double yesterdayClose,
        bool vaildCandle,
        double volume,
        double todayOpenPrice,
        const std::string& gapCheck,
        const std::string& QQQtrendCheck,
        bool priceOptmization)
        : symbol(symbol), atr(atr),
        sma20(sma20),
        sma200(sma200),
        lastPrice(lastPrice),
        vaildtime(vaildtime),
        yesterdayClose(yesterdayClose),
        vaildCandle(vaildCandle),
        volume(volume),
        todayOpenPrice(todayOpenPrice),
        gapCheck(gapCheck),
        QQQtrendCheck(QQQtrendCheck),
        priceOptmization(priceOptmization)
    {
    
    
        while (true) {
            std::cout << "\n" << symbol << " Historical Data Check:" << std::endl;
            std::cout << "1.ATR: " << atr << std::endl;
            std::cout << "2.SMA20: " << sma20 << std::endl;
            std::cout << "3.SMA200: " << sma200 << std::endl;
            std::cout << "4.Last Price: " << lastPrice << std::endl;
            std::cout << "5.VaildTime: " << (vaildtime ? "True" : "False") << std::endl;
            std::cout << "6.Yesterday Close: " << yesterdayClose << std::endl;
            std::cout << "7.vaildCandle: " << (vaildCandle ? "True" : "False") << std::endl;
            std::cout << "8.vaildVolume: " << volume << std::endl;
            std::cout << "9.todayOpenPrice: " << todayOpenPrice << std::endl;
            std::cout << "10.GapCheck: " << gapCheck << std::endl;
            std::cout << "11.QQQtrendCheck: " << QQQtrendCheck << std::endl;
            std::cout << "12.sexyPriceOptimization:" << (priceOptmization ? "True" : "False") << std::endl;

			std::this_thread::sleep_for(std::chrono::seconds(2));
        }
    
    
    
    }
};

