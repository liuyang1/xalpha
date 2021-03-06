# -*- coding: utf-8 -*-
'''
module for trade class
'''
import datetime as dt
import pandas as pd
from pyecharts.charts import Line, Bar
import xalpha.remain as rm
from xalpha.cons import convert_date, xirr, myround, yesterdayobj


def xirrcal(cftable, trades, date, guess):
    '''
    calculate the xirr rate

    :param cftable: cftable (pd.Dateframe) with date and cash column
    :param trades: list [trade1, ...], every item is an trade object,
        whose shares would be sold out virtually
    :param date: string of date or datetime object,
        the date when virtually all holding positions being sold
    :param guess: floating number, a guess at the xirr rate solution to be used
        as a starting point for the numerical solution
    :returns: the IRR as a single floating number
    '''
    date = convert_date(date)
    partcftb = cftable[cftable['date'] <= date]
    if len(partcftb) == 0:
        return 0
    cashflow = [(row['date'], row['cash']) for i, row in partcftb.iterrows()]
    rede = 0
    for fund in trades:
        rede += fund.aim.shuhui(fund.briefdailyreport(date).get('currentshare', 0), date,
                                fund.remtable[fund.remtable['date'] <= date].iloc[-1].rem)[1]
    cashflow.append((date, rede))
    return xirr(cashflow, guess)


def bottleneck(cftable):
    '''
    find the max total input in the history given cftable with cash column

    :param cftable: pd.DataFrame of cftable
    '''
    if len(cftable) == 0:
        return 0
    # cftable = cftable.reset_index(drop=True) # unnecessary as iloc use natural rows instead of default index
    inputl = [-sum(cftable.iloc[:i].cash) for i in range(1, len(cftable) + 1)]
    return myround(max(inputl))


def turnoverrate(cftable, end=yesterdayobj()):
    '''
    calculate the annualized turnoverrate

    :param cftable: pd.DataFrame of cftable
    :param end: str or obj of datetime for the end date of the estimation
    '''
    if len(cftable) == 0:
        return 0
    end = convert_date(end)
    start = cftable.iloc[0].date
    tradeamount = sum(abs(cftable.loc[:, 'cash']))
    turnover = tradeamount / bottleneck(cftable) / 2.
    if (end - start).days <= 0:
        return 0
    return turnover * 365 / (end - start).days


def vtradevolume(cftable, freq='D', bar_category_gap='35%', **vkwds):
    '''
    aid function on visualization of trade summary

    :param cftable: cftable (pandas.DataFrame) with at least date and cash columns
    :param freq: one character string, frequency label, now supporting D for date,
        W for week and M for month, namely the trade volume is shown based on the time unit
    :param vkwds: keyword argument for pyecharts Bar.add()
    :returns: the Bar object
    '''
    if freq == 'D':
        selldata = [[row['date'], row['cash']] for _, row in cftable.iterrows() if row['cash'] > 0]
        buydata = [[row['date'], row['cash']] for _, row in cftable.iterrows() if row['cash'] < 0]
    elif freq == 'W':
        cfmerge = cftable.groupby([cftable['date'].dt.year, cftable['date'].dt.week])['cash'].sum()
        selldata = [[dt.datetime.strptime(str(a) + '4', '(%Y, %W)%w'), b] \
                    for a, b in cfmerge.iteritems() if b > 0]
        buydata = [[dt.datetime.strptime(str(a) + '4', '(%Y, %W)%w'), b] \
                   for a, b in cfmerge.iteritems() if b < 0]
    elif freq == 'M':
        cfmerge = cftable.groupby([cftable['date'].dt.year, cftable['date'].dt.month])['cash'].sum()
        selldata = [[dt.datetime.strptime(str(a) + '15', '(%Y, %m)%d'), b] \
                    for a, b in cfmerge.iteritems() if b > 0]
        buydata = [[dt.datetime.strptime(str(a) + '15', '(%Y, %m)%d'), b] \
                   for a, b in cfmerge.iteritems() if b < 0]
    else:
        raise Exception('no such freq tag supporting')

    bar = Bar()
    bar.add('买入', [0 for _ in range(len(buydata))], buydata, xaxis_type='time', bar_category_gap=bar_category_gap)
    bar.add('卖出', [0 for _ in range(len(selldata))], selldata, xaxis_type='time', is_datazoom_show=True,
            bar_category_gap=bar_category_gap, **vkwds)
    bar
    return bar


class trade():
    '''
    Trade class with fundinfo obj as input and its main attrs are cftable and remtable:

        1. cftable: pd.Dataframe, 现金流量表，每行为不同变更日期，三列分别为 date，cash， share，标记对于某个投资标的
        现金的进出和份额的变化情况，所有的份额数据为交易当时的不复权数据。基金份额折算通过流量表中一次性的份额增减体现。

        2. remtable：pd.Dataframe, 持仓情况表，每行为不同变更日期，两列分别为 date 和 rem， rem 数据结构是一个嵌套的列表，
        包含了不同时间买入仓位的剩余情况，详情参见 remain 模块。这一表格如非必需，避免任何直接调用。

    :param infoobj: info object as the trading aim
    :param status: status table, obtained from record class
    '''

    def __init__(self, infoobj, status):
        self.aim = infoobj
        code = self.aim.code
        self.cftable = pd.DataFrame([], columns=['date', 'cash', 'share'])
        self.remtable = pd.DataFrame([], columns=['date', 'rem'])
        self.status = status.loc[:, ['date', code]]
        self._arrange()

    def _arrange(self):
        while (1):
            try:
                self._addrow()
            except Exception as e:
                if e.args[0] == 'no other info to be add into cashflow table':
                    break
                else:
                    raise e

    def _addrow(self):
        '''
        Return cashflow table with one more line or raise an exception if there is no more line to add
        The same logic also applies to rem table
        关于对于一个基金多个操作存在于同一交易日的说明：无法处理历史买入第一笔同时是分红日的情形, 事实上也不存在这种情形。无法处理一日多笔买卖的情形。
        同一日既有卖也有买不现实，多笔买入只能在 csv 上合并记录，由此可能引起份额计算 0.01 的误差。可以处理分红日买入卖出的情形。
        分级份额折算日封闭无法买入，所以程序直接忽略当天的买卖。因此不会出现多个操作共存的情形。
        '''
        # the design on data remtable is disaster, it is very dangerous though works now

        code = self.aim.code
        if len(self.cftable) == 0:
            if len(self.status[self.status[code] != 0]) == 0:
                raise Exception("no other info to be add into cashflow table")
            i = 0
            while (self.status.iloc[i].loc[code] == 0):
                i += 1
            value = self.status.iloc[i].loc[code]
            date = self.status.iloc[i].date
            if value > 0:
                rdate, cash, share = self.aim.shengou(value, date)
                rem = rm.buy([], share, rdate)
            else:
                raise Exception("You cannot sell first when you never buy")
        elif len(self.cftable) > 0:
            recorddate = list(self.status.date)
            lastdate = self.cftable.iloc[-1].date + pd.Timedelta(1, unit='d')
            while ((lastdate not in self.aim.specialdate) and ((lastdate not in recorddate)
                                                               or ((lastdate in recorddate)
                                                                   and (self.status[
                                                                            self.status['date'] == lastdate].loc[:,
                                                                        code].any() == 0)))):
                lastdate += pd.Timedelta(1, unit='d')
                if (lastdate - yesterdayobj()).days >= 1:
                    raise Exception("no other info to be add into cashflow table")
            date = lastdate
            label = 0
            cash = 0
            share = 0
            rem = self.remtable.iloc[-1].rem
            rdate = date

            if (date in recorddate) and (date not in self.aim.zhesuandate):
                # deal with buy and sell and label the fenhongzaitouru, namely one label a 0.05 in the original table to label fenhongzaitouru
                value = self.status[self.status['date'] == date].iloc[0].loc[code]
                fenhongmark = round(10 * value - int(10 * value), 1)
                if fenhongmark == 0.5:
                    label = 1  # fenhong reinvest
                    value = round(value, 1)

                if value > 0:  # value stands for purchase money
                    rdate, dcash, dshare = self.aim.shengou(value, date)
                    rem = rm.buy(rem, dshare, rdate)

                elif value < -0.005:  # value stands for redemp share
                    rdate, dcash, dshare = self.aim.shuhui(-value, date, self.remtable.iloc[-1].rem)
                    _, rem = rm.sell(rem, -dshare, rdate)
                elif value >= -0.005 and value < 0:
                    # value now stands for the ratio to be sold in terms of remain positions, -0.005 stand for sell 100%
                    remainshare = sum(self.cftable.loc[:, 'share'])
                    ratio = -value / 0.005
                    rdate, dcash, dshare = self.aim.shuhui(remainshare * ratio, date, self.remtable.iloc[-1].rem)
                    _, rem = rm.sell(rem, -dshare, rdate)
                else:  # in case value=0, when specialday is in record day
                    rdate, dcash, dshare = date, 0, 0

                cash += dcash
                share += dshare
            if date in self.aim.specialdate:  # deal with fenhong and xiazhe
                comment = self.aim.price[self.aim.price['date'] == date].iloc[0].loc['comment']
                if isinstance(comment, float):
                    if comment < 0:
                        dcash2, dshare2 = 0, sum([myround(sh * (-comment - 1)) for _, sh in
                                                  rem])  # xiazhe are seperately carried out based on different purchase date
                        rem = rm.trans(rem, -comment, date)
                        # myround(sum(cftable.loc[:,'share'])*(-comment-1))
                    elif comment > 0 and label == 0:
                        dcash2, dshare2 = myround(sum(self.cftable.loc[:, 'share']) * comment), 0
                        rem = rm.copy(rem)

                    elif comment > 0 and label == 1:
                        dcash2, dshare2 = 0, myround(sum(self.cftable.loc[:, 'share']) *
                                                     (comment / self.aim.price[self.aim.price['date'] == date].iloc[
                                                         0].netvalue))
                        rem = rm.buy(rem, dshare2, date)

                    cash += dcash2
                    share += dshare2
                else:
                    raise Exception('comments not recoginized')

        self.cftable = self.cftable.append(pd.DataFrame([[rdate, cash, share]], columns=['date', 'cash', 'share']),
                                           ignore_index=True)
        self.remtable = self.remtable.append(pd.DataFrame([[rdate, rem]], columns=['date', 'rem']), ignore_index=True)

    def xirrrate(self, date=yesterdayobj(), guess=0.1):
        '''
        give the xirr rate for all the trade of the aim before date (virtually sold out on date)

        :param date: string or obj of datetime, the virtually sell-all date
        '''
        return xirrcal(self.cftable, [self], date, guess)

    def dailyreport(self, date=yesterdayobj()):
        '''
        breif report dict of certain date status on the fund investment

        :param date: string or obj of date, show info of the date given
        :returns: dict of various data on the trade positions
        '''
        date = convert_date(date)
        partcftb = self.cftable[self.cftable['date'] <= date]
        value = self.aim.price[self.aim.price['date'] <= date].iloc[-1].netvalue

        if len(partcftb) == 0:
            reportdict = {'基金名称': [self.aim.name], '基金代码': [self.aim.code], '当日净值': [value], '持有份额': [0],
                          '基金现值': [0], '基金总申购': [0], '历史最大占用': [0], '基金分红与赎回': [0], '基金收益总额': [0]}
            df = pd.DataFrame(reportdict, columns=reportdict.keys())
            return df
        # totinput = myround(-sum(partcftb.loc[:,'cash']))
        totinput = myround(-sum([row['cash'] for _, row in partcftb.iterrows() if row['cash'] < 0]))
        totoutput = myround(sum([row['cash'] for _, row in partcftb.iterrows() if row['cash'] > 0]))

        currentshare = myround(sum(partcftb.loc[:, 'share']))
        currentcash = myround(currentshare * value)
        btnk = bottleneck(partcftb)
        turnover = turnoverrate(partcftb, date)
        ereturn = myround(currentcash + totoutput - totinput)
        if currentshare == 0:
            unitcost = 0
        else:
            unitcost = round((totinput - totoutput) / currentshare, 4)
        if btnk == 0:
            returnrate = 0
        else:
            returnrate = round((ereturn / btnk) * 100, 4)

        reportdict = {'基金名称': [self.aim.name], '基金代码': [self.aim.code], '当日净值': [value], '单位成本': [unitcost],
                      '持有份额': [currentshare], '基金现值': [currentcash], '基金总申购': [totinput], '历史最大占用': [btnk],
                      '基金持有成本': [totinput - totoutput],
                      '基金分红与赎回': [totoutput], '换手率': [turnover], '基金收益总额': [ereturn], '投资收益率': [returnrate]}
        df = pd.DataFrame(reportdict, columns=reportdict.keys())
        return df

    def briefdailyreport(self, date=yesterdayobj()):
        '''
        quick summary of highly used attrs for trade

        :param date: string or object of datetime
        :returns: dict with several attrs: date, unitvalue, currentshare, currentvalue
        '''
        date = convert_date(date)
        partcftb = self.cftable[self.cftable['date'] <= date]
        if len(partcftb) == 0:
            return {}

        unitvalue = self.aim.price[self.aim.price['date'] <= date].iloc[-1].netvalue
        currentshare = myround(sum(partcftb.loc[:, 'share']))
        currentvalue = myround(currentshare * unitvalue)

        return {'date': date, 'unitvalue': unitvalue, 'currentshare': currentshare,
                'currentvalue': currentvalue}

    def unitcost(self, date=yesterdayobj()):
        '''
        give the unitcost of fund positions

        :param date: string or object of datetime
        :returns: float number of unitcost
        '''
        partcftb = self.cftable[self.cftable['date'] <= date]
        if len(partcftb) == 0:
            return 0
        totnetinput = myround(-sum(partcftb.loc[:, 'cash']))
        currentshare = self.briefdailyreport(date).get('currentshare', 0)
        totnetinput
        if currentshare > 0:
            unitcost = totnetinput / currentshare
        else:
            unitcost = 0
        return unitcost

    def v_tradevolume(self, **vkwds):
        '''
        visualization on trade summary

        :param vkwds: keyword argument for pyecharts Bar.add(), and freq= label,
            please ref to the API of trade.vtradevolume function
        :returns: pyecharts.bar
        '''
        return vtradevolume(self.cftable, **vkwds)

    def v_tradecost(self, start=None, end=yesterdayobj(), **vkwds):
        '''
        visualization giving the average cost line together with netvalue line

        :param vkwds: keywords options for line.add()
        :returns: pyecharts.line
        '''
        funddata = []
        costdata = []
        pprice = self.aim.price[self.aim.price['date'] <= end]
        if start is not None:
            pprice = pprice[pprice['date'] >= start]
        for _, row in pprice.iterrows():
            date = row['date']
            funddata.append([date, row['netvalue']])
            if (date - self.cftable.iloc[0].date).days >= 0:
                cost = self.unitcost(date)
                costdata.append([date, cost])

        line = Line()
        line.add('fundvalue', [1 for _ in range(len(funddata))], funddata, **vkwds)
        line.add('average_cost', [1 for _ in range(len(costdata))], costdata,
                 is_datazoom_show=True, xaxis_type="time", **vkwds)

        return line

    def v_totvalue(self, end=yesterdayobj(), **vkwds):
        '''
        visualization on the total values daily change of the aim
        '''
        valuedata = []
        partp = self.aim.price[self.aim.price['date'] >= self.cftable.iloc[0].date]
        partp = partp[partp['date'] <= end]
        for i, row in partp.iterrows():
            date = row['date']
            valuedata.append([date, self.briefdailyreport(date).get('currentvalue', 0)])

        line = Line()
        line.add('totvalue', [1 for _ in range(len(valuedata))], valuedata,
                 is_datazoom_show=True, xaxis_type="time", **vkwds)

        return line

    def __repr__(self):
        return self.aim.name + ' 交易情况'


'''
可视化图的合并可参考以下代码
from pyecharts import Overlap
overlap = Overlap()
overlap.add(self.v_tradecost())
overlap.add(self.v_tradevolume(bar_category_gap='95%'), yaxis_index=1,is_add_yaxis=True)
overlap
'''
