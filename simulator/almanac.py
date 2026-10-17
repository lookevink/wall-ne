"""Orchard almanac: day counter, sun path, weather and per-tree ecology between missions.

A day's conditions are fixed when its mission is created and saved with that
mission's checkpoint. Missions own physical care during the day; this module
only turns one day's physical end state into the next morning. Quantities are
simulation parameters, not agronomic advice.
"""
import copy
import hashlib
import math
import random
from .engine import TERMINAL
from .orchard_manipulation import TREES

LATITUDE=36.7           # Central Valley almond country
SOLAR_NOON=13*3600+600  # local daylight-saving time
FIRST_DAY=152           # season day 1 is 2 June
DAY=86400
# Trunk-face pest slots (x offset, height), each >0.2 m from the ladybird at (-.08, 1.15).
PEST_SLOTS=((.075,.45),(-.075,.73),(.07,.98),(-.07,.27))
# Growth stays inside the validated wrist-camera specimen range (size .9-1.2, 9-15 leaves).
SPROUT=dict(size=.9,leaves=9)
MATURE=dict(size=1.2,leaves=15)


def care_trees(count=10):
    # Front boundary trees have a clear approach from the public south apron.
    return sorted((t for t in TREES if t['column']==12),key=lambda t:abs(t['row']-6))[:count]


def weather(seed,day):
    rng=random.Random(seed*7919+day*104729+17)
    rain=round(rng.uniform(3,14),1) if day>1 and rng.random()<.14 else 0.
    high=min(40,max(23,31+rng.gauss(0,3.5)-rain*.35))
    return dict(high=round(high,1),low=round(high-rng.uniform(12,16),1),humidity=round(min(82,max(24,46+rng.gauss(0,9)+rain*1.6)),1),
                cloud=round(min(.9,rng.random()**2*.6+rain*.03),2),rain=rain)


def declination(day_of_year):
    return math.radians(23.44)*math.sin(2*math.pi*(284+day_of_year)/365)


def sun_times(day_of_year):
    """Sunrise and sunset, seconds after local midnight (refraction-corrected horizon)."""
    phi,d=math.radians(LATITUDE),declination(day_of_year)
    half=math.degrees(math.acos((math.sin(math.radians(-.833))-math.sin(phi)*math.sin(d))/(math.cos(phi)*math.cos(d))))
    return SOLAR_NOON-half*240,SOLAR_NOON+half*240


def sun_position(day_of_year,clock):
    """Elevation and azimuth (clockwise from north) in degrees."""
    phi,d,h=math.radians(LATITUDE),declination(day_of_year),math.radians((clock-SOLAR_NOON)/240)
    elevation=math.asin(math.sin(phi)*math.sin(d)+math.cos(phi)*math.cos(d)*math.cos(h))
    azimuth=math.atan2(math.sin(h),math.cos(h)*math.sin(phi)-math.tan(d)*math.cos(phi))+math.pi
    return math.degrees(elevation),math.degrees(azimuth)%360


def direction(elevation,azimuth):
    # Scene axes: east is +x, up is +y, north is -z.
    e,a=math.radians(elevation),math.radians(azimuth)
    return [round(math.sin(a)*math.cos(e),5),round(math.sin(e),5),round(-math.cos(a)*math.cos(e),5)]


def weed_spec(seed,day,index,age=0):
    specimen=int(hashlib.sha256(f'weed:{seed}:{day}:{index}'.encode()).hexdigest()[:7],16)
    spec=dict(specimen_seed=specimen,sprouted=day-age,age=age);grow(spec);return spec


def grow(spec):
    spec.update(size=round(min(MATURE['size'],SPROUT['size']+.06*spec['age']),3),leaves=min(MATURE['leaves'],SPROUT['leaves']+spec['age']))


def prescription(deficit):
    return min(30,round(deficit)) if deficit>=12 else 0


class Season:
    """One orchard's calendar. Day 0 is the night before the first mission."""
    def __init__(self,seed=7,day=0,trees=None,history=None,previous=None):
        if type(seed)!=int or not 0<=seed<=100000:raise ValueError('seed must be 0..100000')
        self.seed=seed;self.day=day;self.history=history or [];self.previous=previous
        self.day_of_year=FIRST_DAY+day-1;self.weather=weather(seed,day)
        self.trees=trees if trees is not None else self.initial_trees()

    def initial_trees(self):
        trees=[]
        for i,tree in enumerate(care_trees()):
            rng=random.Random(self.seed*31337+i)
            trees.append(dict(index=i,tree=copy.deepcopy(tree),moisture=round(rng.uniform(20,40),2),weed=weed_spec(self.seed,0,i,rng.randint(0,3)),
                              pests=rng.randint(1,3),deficit=round(rng.uniform(12,20),2)))
        return trees

    def conditions(self):
        """Morning state of each care tree, in care-mission task order."""
        return [dict(index=t['index'],tree=t['tree'],moisture=t['moisture'],weed=copy.deepcopy(t['weed']),pests=t['pests'],prescription=prescription(t['deficit'])) for t in self.trees]

    def view_trees(self,live=None):
        """Each care tree's morning conditions with the day's measured state so far, for operator views."""
        live=live or {};trees=[]
        for c in self.conditions():
            o=live.get(c['index'],{})
            trees.append(dict(index=c['index'],row=c['tree']['row'],position=c['tree']['position'],morning_moisture=c['moisture'],moisture=o.get('moisture',c['moisture']),
                              weed_age=c['weed']['age'],weed_size=c['weed']['size'],weed_removed=bool(o.get('weed_removed')),pests=c['pests'],
                              pests_remaining=o.get('pests_remaining',c['pests']),prescription=c['prescription'],cared=bool(o.get('cared'))))
        return trees

    def next_day(self,outcomes=None):
        """Apply today's physical end state, then tonight's weather, to tomorrow morning.

        outcomes maps care-tree index to measured end state (moisture, fertilizer,
        weed_removed, pests_remaining, cared). Trees without an outcome were not touched.
        """
        outcomes={int(k):v for k,v in (outcomes or {}).items()}
        today,tonight=self.weather,weather(self.seed,self.day+1)
        dry=min(13,max(2.5,5+.45*(today['high']-28)+.09*(55-today['humidity'])))
        breed=min(.7,max(.1,.3+.03*(today['high']-30)));arrive=min(.7,max(.08,.3+.005*(today['humidity']-50)+.02*(today['high']-30)))
        trees=[];tally=dict(day=self.day,cared=0,weeds_pulled=0,pests_removed=0,water=0.,fertilizer=0.)
        for t in self.trees:
            rng=random.Random(f'night:{self.seed}:{self.day}:{t["index"]}');o=outcomes.get(t['index'],{})
            end=o.get('moisture',t['moisture']);tally['water']+=max(0,end-t['moisture'])/2
            weed=copy.deepcopy(t['weed'])
            if o.get('weed_removed'):weed=weed_spec(self.seed,self.day+1,t['index']);tally['weeds_pulled']+=1
            else:weed['age']+=1;grow(weed)
            pests=min(t['pests'],max(0,o.get('pests_remaining',t['pests'])));tally['pests_removed']+=t['pests']-pests
            pests+=sum(rng.random()<breed for _ in range(pests))+(rng.random()<arrive)
            if pests and rng.random()<.25:pests-=1  # the resident ladybird
            applied=max(0,o.get('fertilizer',0));tally['fertilizer']+=applied;tally['cared']+=bool(o.get('cared'))
            trees.append(dict(t,moisture=round(min(58,max(10,end-dry+tonight['rain']*1.6)),2),weed=weed,pests=min(len(PEST_SLOTS),pests),deficit=round(min(30,max(0,t['deficit']-applied)+4),2)))
        tally.update(water=round(tally['water'],1),fertilizer=round(tally['fertilizer'],1),high=today['high'],humidity=today['humidity'])
        history=(self.history+[tally])[-90:] if self.day else self.history
        return Season(self.seed,self.day+1,trees,history,dict(day=self.day,drying=round(dry,2),outcomes={str(k):v for k,v in outcomes.items()}))

    def humidity(self,clock):
        # Relative humidity peaks just before dawn and bottoms out mid-afternoon.
        return min(99,max(12,self.weather['humidity']+26*math.cos(2*math.pi*(clock-5.5*3600)/DAY)))

    def temperature(self,clock):
        w=self.weather;return (w['high']+w['low'])/2+(w['high']-w['low'])/2*math.cos(2*math.pi*(clock-15.5*3600)/DAY)

    def environment(self,clock):
        sunrise,sunset=sun_times(self.day_of_year);elevation,azimuth=sun_position(self.day_of_year,clock)
        humidity=self.humidity(clock);mist=min(1,max(0,(humidity-78)/16))
        hours=clock/3600;morning=clock<SOLAR_NOON
        phase=('night' if elevation<-6 else ('dawn' if morning else 'dusk') if elevation<0 else ('sunrise' if morning else 'golden hour') if elevation<12
               else 'morning' if hours<11 else 'midday' if hours<15.5 else 'afternoon')
        moon=(min(65,max(15,10-elevation*.7)),(azimuth+200)%360)
        return dict(clock=round(clock,1),label=f'{int(hours)%24:02d}:{int(clock%3600//60):02d}',sunrise=round(sunrise),sunset=round(sunset),phase=phase,
                    sun=dict(elevation=round(elevation,3),azimuth=round(azimuth,3),direction=direction(elevation,azimuth)),
                    moon=dict(elevation=round(moon[0],3),direction=direction(*moon)),humidity=round(humidity,1),temperature=round(self.temperature(clock),1),
                    mist=round(mist,3),cloud=self.weather['cloud'],weather=self.weather)

    def record(self):
        sunrise,sunset=sun_times(self.day_of_year)
        return copy.deepcopy(dict(seed=self.seed,day=self.day,day_of_year=self.day_of_year,weather=self.weather,sunrise=round(sunrise),sunset=round(sunset),
                                  trees=self.trees,history=self.history,previous=self.previous))

    @classmethod
    def from_record(cls,record):
        return cls(record['seed'],record['day'],copy.deepcopy(record['trees']),copy.deepcopy(record.get('history',[])),copy.deepcopy(record.get('previous')))


class DayClock:
    """Operator-facing orchard time of day.

    It runs at the working pace while the day's mission runs, freezes while the
    mission is paused, and sweeps through to nightfall once the mission settles.
    It never feeds back into mission physics or decision observations.
    """
    LEAD=26*60  # robots roll out in civil twilight
    CAP=DAY-60

    def __init__(self,season,day_minutes=20,auto_advance=False):
        self.day_minutes=day_minutes;self.auto_advance=auto_advance;self.reset(season)

    def reset(self,season,clock=None):
        self.season=season;self.sunrise,self.sunset=sun_times(season.day_of_year)
        self.night=min(self.sunset+80*60,DAY-30*60)
        self.clock=clock if clock is not None else self.night if season.day==0 else self.sunrise-self.LEAD
        self.mode='night' if season.day==0 else 'working';self.rate=0.;self.fast=None;self.night_since=None

    def work_rate(self):
        return (self.sunset-self.sunrise)/(self.day_minutes*60)

    def tick(self,elapsed,status,now):
        if self.season.day==0:mode='night'
        elif status=='running':mode='working'
        elif status in TERMINAL:mode='settling' if self.clock<self.night else 'night'
        else:mode='paused'
        if mode=='settling' and self.fast is None:self.fast=max(self.work_rate(),(self.night-self.clock)/45)
        rate=self.work_rate() if mode=='working' else self.fast if mode=='settling' else 0.
        self.clock=min(self.CAP,self.clock+rate*elapsed)
        if mode=='settling' and self.clock>=self.night:mode,rate='night',0.
        self.night_since=(self.night_since or now) if mode=='night' else None
        self.mode=mode;self.rate=rate

    def due(self,now,hold=6):
        return self.auto_advance and self.season.day>0 and self.mode=='night' and self.night_since is not None and now-self.night_since>=hold

    def view(self):
        return dict(self.season.environment(self.clock),day=self.season.day,seed=self.season.seed,mode=self.mode,rate=round(self.rate,3),
                    day_minutes=self.day_minutes,auto_advance=self.auto_advance,night=round(self.night))
