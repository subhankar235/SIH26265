from pydantic import BaseModel
class MetricCards(BaseModel): total_active_value:float=0; expiring_30d:int=0; pending_verifications:int=0; discrepancies_flagged:int=0
class ChartPoint(BaseModel): label:str; value:float
class DashboardOut(BaseModel): metrics:MetricCards; value_by_bank:list[ChartPoint]=[]; maturity_timeline:list[ChartPoint]=[]; status_breakdown:list[ChartPoint]=[]
