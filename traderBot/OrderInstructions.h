#pragma once
#include <Decimal.h>
struct OrderInstructions
{
	std::string action;
	double stopLoss;
	Decimal quantity;
	bool valid;
	double price;
	
	
};