# -*- coding: utf-8 -*-
'''
modules for evaluation and comparison on multiple object with price dataframe
'''

import pandas as pd
from pyecharts.charts import Line, HeatMap
from xalpha.cons import convert_date, yesterdayobj


class evaluate():
    '''
    多个 info 对象的比较类，比较的对象只要实现了 price 属性，该属性为具有 date 和 netvalue 列的 pandas.DataFrame 即可。
    更进一步，也可讲做过 bcmkset 的 :class:`xalpha.multiple.mulfix` 类作为输入，只不过此时需要提前额外指定以下该对象的 name 和 code 两个属性。
    由于该类需要各基金净值表可以严格对齐，因此需要对节假日和国内不同的 QDII 基金进行补齐，由于第一个基金为基准，因此第一个输入不建议是 QDII 基金

    :param fundobjs: info object，或者如前所述一切具有 price 表的对象
    :param start: date string or object, 比较的起始时间，默认使用所有 price 表中最近的起始时间。
        但需要注意，由于拉取的基金净值表，往往在开始几天缺失净值数据，即使使用默认时间也可能无法对齐所有净值数据。
        因此建议手动设置起始时间到最近的起始时间一周后左右。 
    '''

    def __init__(self, *fundobjs, start=None):
        self.fundobjs = fundobjs
        self.totprice = self.fundobjs[0].price[['date', 'netvalue']].rename(columns={'netvalue': fundobjs[0].code})
        for fundobj in fundobjs[1:]:
            self.totprice = self.totprice.merge(fundobj.price[['date', 'netvalue']].
                                                rename(columns={'netvalue': fundobj.code}), on='date')

        startdate = self.totprice.iloc[0].date
        if start is None:
            self.start = startdate
        else:
            start = convert_date(start)
            if start < startdate:
                raise Exception('Too early start date')
            else:
                self.start = start
                self.totprice = self.totprice[self.totprice['date'] >= self.start]
        self.totprice = self.totprice.reset_index(drop=True)
        for col in self.totprice.columns:
            if col != 'date':
                self.totprice[col] = self.totprice[col] / self.totprice[col].iloc[0]

    def v_netvalue(self, end=yesterdayobj(), **vkwds):
        '''
        起点对齐归一的，各参考基金或指数的净值比较可视化

        :param end: string or object of date, the end date of the line
        :param vkwds: pyechart line.add() options
        :returns: pyecharts.Line object
        '''
        partprice = self.totprice[self.totprice['date'] <= end]
        xdata = [1 for _ in range(len(partprice))]
        ydatas = []
        for fund in self.fundobjs:
            ydata = [[row['date'], row[fund.code]] for _, row in partprice.iterrows()]
            ydatas.append(ydata)
        line = Line()
        for i, fund in enumerate(self.fundobjs):
            line.add(fund.name, xdata, ydatas[i], is_datazoom_show=True, xaxis_type="time", **vkwds)
        return line

    def correlation_table(self, end=yesterdayobj()):
        '''
        give the correlation coefficient amongst referenced funds and indexes

        :param end: string or object of date, the end date of the line
        :returns: pandas DataFrame, with correlation coefficient as elements
        '''
        partprice = self.totprice[self.totprice['date'] <= end]
        covtable = partprice.iloc[:, 1:].pct_change().corr()
        return covtable

    def v_correlation(self, end=yesterdayobj(), **vkwds):
        '''
        各基金净值的相关程度热力图可视化

        :param end: string or object of date, the end date of the line
        :returns: pyecharts.Heatmap object
        '''
        ctable = self.correlation_table(end)
        x_axis = list(ctable.columns)
        data = [[i, j, ctable.iloc[i, j]] for i in range(len(ctable)) for j in range(len(ctable))]
        heatmap = HeatMap()
        heatmap.add("", x_axis, x_axis, data, is_visualmap=True, visual_pos='center',
                    visual_text_color="#000", visual_range=[-1, 1], visual_orient='horizontal', **vkwds)
        return heatmap
