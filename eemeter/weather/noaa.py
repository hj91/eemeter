from .cache import CachedWeatherSourceBase
from .clients import NOAAClient

from datetime import datetime, date, timedelta

import pandas as pd
import pytz


class NOAAWeatherSourceBase(CachedWeatherSourceBase):

    year_existence_format = None
    client = NOAAClient()

    def __init__(self, station, start_year=None, end_year=None,
                 cache_directory=None, cache_filename=None):
        super(NOAAWeatherSourceBase, self).__init__(
                station, cache_directory, cache_filename)

        self._year_fetches_attempted = set()

        self.station_id = station

        if start_year is not None and end_year is not None:
            self.add_year_range(start_year, end_year)
        elif start_year is not None:
            self.add_year_range(start_year, date.today().year)
        elif end_year is not None:
            self.add_year_range(date.today().year, end_year)

        self._check_for_recent_data()

    def add_year_range(self, start_year, end_year, force=False):
        """Adds temperature data to internal pandas timeseries across a
        range of years.

        Parameters
        ----------
        start_year : {int, string}
            The earliest year for which data should be fetched, e.g. "2010".
        end_year : {int, string}
            The latest year for which data should be fetched, e.g. "2013".
        force : bool, default=False
            If True, forces the fetch; if false, checks to see if year
            has been added before actually fetching.
        """
        for year in range(start_year, end_year + 1):
            self.add_year(year, force)

    def add_year(self, year, force=False):
        message = "Inheriting classes must override this method."
        raise NotImplementedError(message)

    def _year_fetch_attempted(self, year):
        return year in self._year_fetches_attempted

    def _year_in_series(self, year):
        return self.year_existence_format.format(year) in self.tempC

    def _check_for_recent_data(self):
        yesterday = date.today() - timedelta(days=1)
        if yesterday in self.tempC and pd.isnull(self.tempC[yesterday]):
            self.add_year(yesterday.year, force=True)

    def indexed_temperatures(self, index, unit):
        ''' Return average temperatures over the given index.

        Parameters
        ----------
        index : pandas.DatetimeIndex
            Index over which to supply average temperatures.
            The :code:`index` should be given as either an hourly ('H') or
            daily ('D') frequency.
        unit : str, {"degF", "degC"}
            Target temperature unit for returned temperature series.

        Returns
        -------
        temperatures : pandas.Series with DatetimeIndex
            Average temperatures over series indexed by :code:`index`.
        '''
        self._verify_index_presence(index)

        if index.freq == 'D':
            return self._daily_indexed_temperatures(index, unit)
        elif index.freq == 'H':
            return self._hourly_indexed_temperatures(index, unit)
        else:
            message = (
                'DatetimeIndex frequency "{}" not supported, please resample.'
                .format(index.freq)
            )
            raise ValueError(message)

    def _daily_indexed_temperatures(self, index, unit):
        tempC = self.tempC.resample('D').mean()[index]
        return self._unit_convert(tempC, unit)

    def _hourly_indexed_temperatures(self, index, unit):
        message = (
            'DatetimeIndex frequency "H" not supported,'
            ' please resample to at least daily frequency ("D").'
            .format(index.freq)
        )
        raise ValueError(message)

    def _verify_index_presence(self, index):
        if index.shape == (0,):
            return  # don't need to fetch anything.
        years = index.groupby(index.year).keys()
        for year in years:
            self.add_year(year)


class GSODWeatherSource(NOAAWeatherSourceBase):

    cache_date_format = "%Y%m%d"
    cache_filename_format = "GSOD-{}.json"
    year_existence_format = "{}-01-01"
    freq = "D"

    def _empty_series(self, year):
        dates = pd.date_range("{}-01-01 00:00".format(year),
                              "{}-12-31 00:00".format(year),
                              freq=self.freq, tz=pytz.UTC)
        return pd.Series(None, index=dates, dtype=float)

    def add_year(self, year, force=False):
        """Adds temperature data to internal pandas timeseries

        Parameters
        ----------
        year : {int, string}
            The year for which data should be fetched, e.g. "2010".
        force : bool, default=False
            If True, forces the fetch; if false, checks to see if year
            has been added before actually fetching.
        """

        if not force and self._year_fetch_attempted(year):
            if self._year_in_series(year):
                return
            else:
                new_series = self._empty_series(year)
                self.tempC = self.tempC.append(new_series) \
                    .sort_index().resample(self.freq).mean()
                self.save_to_cache()
                return

        data = self.client.get_gsod_data(self.station, year)
        new_series = self._empty_series(year)
        for day in data:
            if not pd.isnull(day["temp_C"]):
                new_series[day["date"]] = day["temp_C"]

        # changed for pandas > 0.18
        self.tempC = self.tempC.append(new_series) \
            .sort_index().resample(self.freq).mean()
        self.save_to_cache()
        self._year_fetches_attempted.add(year)


class ISDWeatherSource(NOAAWeatherSourceBase):

    cache_date_format = "%Y%m%d%H"
    cache_filename_format = "ISD-{}.json"
    year_existence_format = "{}-01-01 00"
    freq = "H"

    def _empty_series(self, year):
        dates = pd.date_range("{}-01-01 00:00".format(year),
                              "{}-01-01 00:00".format(int(year) + 1),
                              freq=self.freq, tz=pytz.UTC)[:-1]
        return pd.Series(None, index=dates, dtype=float)

    def add_year(self, year, force=False):
        """Adds temperature data to internal pandas timeseries

        Parameters
        ----------
        year : {int, string}
            The year for which data should be fetched, e.g. "2010".
        """
        if not force and self._year_fetch_attempted(year):
            if self._year_in_series(year):
                return
            else:
                new_series = self._empty_series(year)
                self.tempC = self.tempC.append(new_series) \
                    .sort_index().resample(self.freq).mean()
                self.save_to_cache()
                return

        data = self.client.get_isd_data(self.station, year)
        new_series = self._empty_series(year)
        for hour in data:
            if not pd.isnull(hour["temp_C"]):
                dt = hour["datetime"]
                new_dt = datetime(dt.year, dt.month, dt.day, dt.hour)
                new_series[new_dt] = hour["temp_C"]

        # changed for pandas > 0.18
        self.tempC = self.tempC.append(new_series) \
            .sort_index().resample(self.freq).mean()
        self.save_to_cache()
        self._year_fetches_attempted.add(year)

    def _hourly_indexed_temperatures(self, index, unit):
        tempC = self.tempC.resample('H').mean()[index]
        return self._unit_convert(tempC, unit)
