#pragma once
#include <iostream>
#include "DefaultEWrapper.h"
#include "EWrapper.h"
#include "EClientSocket.h"
#include "EReader.h"
#include "EReaderOSSignal.h"
#include "Contract.h"
#include "TagValue.h"
#include "Order.h"
#include "Decimal.h"
#include "DataFetcher.h"
#include <mutex>



class IbApi : public DefaultEWrapper {

public:
    EReaderOSSignal signal;
    EClientSocket* client = nullptr;
    std::unordered_map<int, std::vector<double>>marketData;
    std::unordered_map<int, std::vector<Bar>> barsByReqId;
    std::unordered_map<TickerId, std::string> symbolByReqId;
    std::mutex barsMutex;
    std::mutex symbolMutex;
    std::condition_variable historicalCv;
    std::unordered_set<int> completedRequests;
    std::atomic<int> idCounter{0};
    std::atomic<OrderId> m_nextValidId{ -1 };


    EClientSocket* getClient() { return client; }
    void error(int id, time_t errorTime, int errorCode, const std::string& errorString, const std::string& advancedOrderRejectJson) override;
    void tickPrice(TickerId tickerId, TickType field, double price, const TickAttrib& attrib) override;
    void historicalDataUpdate(TickerId reqId, const Bar& bar) override;
    void historicalData(TickerId reqId, const Bar& bar) override;
    void sendMarketData(int tickerId, std::vector<double>& target);
    int getATRbars(std::string symbol);
	int getSma20bars(std::string symbol);
    int getSma200bars(std::string symbol);
    int getLastPrice(std::string symbol);
    int getYesderdayClose(std::string symbol);
    void setClient(EClientSocket* value) {
        client = value;
    }
    void nextValidId(OrderId brokerNextId) override {
        OrderId current = m_nextValidId.load();

        while (current < brokerNextId &&
            !m_nextValidId.compare_exchange_weak(
                current, brokerNextId)) {
        }

        std::cout << "Next available order ID: "
            << m_nextValidId.load() << '\n';
    }
    void registerSymbol(TickerId reqId, const std::string& symbol) {
        std::lock_guard<std::mutex> lock(symbolMutex);
        symbolByReqId[reqId] = symbol;
    }
    void historicalDataEnd(
        int reqId,
        const std::string& start,
        const std::string& end)override;

    virtual void realtimeBar(TickerId reqId, long time, double open, double high,
        double low, double close, Decimal volume,
        Decimal wap, int count) override;
    // Checks readiness without consuming an ID.
    bool hasValidOrderId() const {
        return m_nextValidId.load() >= 0;
    }

    // Used only for market-data requests.
    int getNextRequestId() {
        return ++idCounter;
    }

    // Used only when creating an order.
    OrderId getNextOrderId() {
        if (!hasValidOrderId()) {
            throw std::logic_error("IBKR order ID is not ready");
        }

        return m_nextValidId.fetch_add(1);
    }
    std::vector<Bar>* getptrbar(TickerId reqId) {
        std::lock_guard<std::mutex> lock(barsMutex);
        return &barsByReqId[reqId];
    }




};
