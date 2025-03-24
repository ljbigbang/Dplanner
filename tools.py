#write event list to mongodb
from pymongo import MongoClient
from datetime import datetime, timedelta 

#check Conflict 
def check_time_conflicts(list_a, list_b):
    conflicts = []
    
    for event_a in list_a:
        start_a = event_a["start_time"]
        if isinstance(start_a, str):
            start_a = datetime.strptime(start_a, "%Y-%m-%d %H:%M")
        end_a = event_a["end_time"]
        if isinstance(end_a, str):
            end_a = datetime.strptime(end_a, "%Y-%m-%d %H:%M")
        
        for event_b in list_b:
            start_b = event_b["start_time"]
            if isinstance(start_b, str):
                start_b = datetime.strptime(start_b, "%Y-%m-%d %H:%M")
            end_b = event_b["end_time"]
            if isinstance(end_b, str):
                end_b = datetime.strptime(end_b, "%Y-%m-%d %H:%M")

            # Check for time overlap
            if ( (start_a <= end_b and  start_a >= start_b ) or ( end_a >= start_b and end_a <= end_b)) :
                conflicts.append({
                    "event_a_id": event_a["event_id"],
                    "event_b_id": event_b["event_id"],
                    "conflict_period": {
                        "start": max(start_a, start_b),
                        "end": min(end_a, end_b)
                    }
                })
    
    return conflicts

#receive a check json, and return the json with status
    # "event_id": "random_alphanumeric", 
    # "start_time": "YYYY-MM-DD HH:MM", (required)
    # "end_time": "YYYY-MM-DD HH:MM",   
    # "category": "Work/Personal/Health",
    # "description": "user input",
    # "priority": "1-5"

class EventDatabase:
    def __init__(self):
        self.client = MongoClient('mongodb+srv://chrispeng912:hdKhfSgWYWSCcqvf@agent.aosmv.mongodb.net/?retryWrites=true&w=majority&appName=agent')
        self.db = self.client['schedule_db']
        self.events = self.db['events'] # collectioin
        
        # Create indexes for efficient querying
        self.events.create_index("event_id")
        self.events.create_index("start_time")
        self.events.create_index("category")

    def add_event(self, event):
        # Convert string dates to datetime objects
        event['start_time'] = datetime.strptime(event['start_time'], "%Y-%m-%d %H:%M")
        event['end_time'] = datetime.strptime(event['end_time'], "%Y-%m-%d %H:%M")
        return self.events.insert_one(event)

    def get_event_by_id(self, event_id):
        
        return self.events.find_one({"event_id": event_id})

    def get_event_by_date(self,event_date):

        start_of_day = datetime(event_date.year, event_date.month, event_date.day)
        end_of_day = start_of_day + timedelta(days=1)
        return self.events.find({
            "start_time": {
                "$gte": start_of_day,
                "$lt": end_of_day
            }
        })


    def get_events_by_time_range(self, start_time, end_time):
        return self.events.find({
            "start_time": {
                "$gte": datetime.strptime(start_time, "%Y-%m-%d %H:%M"),
                "$lte": datetime.strptime(end_time, "%Y-%m-%d %H:%M")
            }
        })

    def get_events_by_category(self, category):
        return self.events.find({"category": category})

    def get_events_by_criteria(self, criteria=None):
        """
        Combined search with multiple conditions
        """
        if criteria is None:
            criteria = {}
            
        query = {}
        # Handle time range
        if 'start_time' in criteria :
            query['start_time'] = {}
            query['end_time'] = {}
            query['start_time']['$gte'] = criteria['start_time']
            query['end_time']['$lte'] = criteria['end_time']
                
        # Handle other criteria
        for field in ['category', 'priority', 'event_id']:
            if field in criteria:
                query[field] = criteria[field]
        #content search
        if 'description' in criteria:
            query['description'] = {'$regex': criteria['description'], '$options': 'i'}
 
        return self.events.find(query)



    def get_events_by_time_range(self, start_time, end_time):
        return self.events.find({
            "start_time": {
                "$gte": datetime.strptime(start_time, "%Y-%m-%d %H:%M"),
                "$lte": datetime.strptime(end_time, "%Y-%m-%d %H:%M")
            }
        })

    def get_events_by_category(self, category):
        return self.events.find({"category": category})

    def delete_by_id(self, event_id):
        """
        Delete an event by its event_id
        Returns: DeleteResult object with deleted_count property
        """
        result = self.events.delete_one({"event_id": event_id})
        return result

# get the existed events that is same date of the add event
def get_add_event(list_a):
    get_events = []
#    seen_dates = set()
    db=EventDatabase()
    for event in list_a:
        event_date = event['start_time']
        #check if data is str,turn to datetime
        if isinstance(event_date, str):
            event_date = datetime.strptime(event_date, "%Y-%m-%d %H:%M")
        found_event=[doc for doc in db.get_event_by_date(event_date)]
        get_events.extend(found_event)
    return get_events
    #     if date_str not in seen_dates:
    #         seen_dates.add(date_str)
    #         stats.append({
    #             "search_date": date_str
    #         })
    
    # return stats

#this func should use the require info to retrieve event from the database
def get_event(list_a):
    event_list=[]
    db=EventDatabase()
    for e in list_a:
        #check if data is str,turn to datetime
        if isinstance(e['start_time'], str):
            e['start_time'] = datetime.strptime(e['start_time'], "%Y-%m-%d %H:%M")
        if isinstance(e['end_time'], str):
            e['end_time'] = datetime.strptime(e['end_time'], "%Y-%m-%d %H:%M")
        found_event=[doc for doc in db.get_events_by_criteria(e)]
        event_list=event_list.extend(found_event) 
    return event_list

#this func should use the require info to write event to the database
def write_event(list_event):
    #first check the event if, if already in the db, delete first
    db = EventDatabase()
    for event in list_event:
        if db.get_event_by_id(event['event_id']):
            db.delete_by_id(event['event_id'])
        db.add_event(event)

def delete_event(list_event):
    db = EventDatabase()
    for event in list_event:
        if db.get_event_by_id(event['event_id']):
            db.delete_by_id(event['event_id'])

#extract part from the llm response
def extract_message(response, field):
    # Find the grounded message between quotes
    if field in response:
        # Split by grounded message: and get the part after it
        message_part = response.lower().split("grounded message:")[1].strip()
        # Extract content between quotes
        try:
            message = message_part.split('collected events:')[0]
            return message
        except IndexError:
            return None
    return None

def get_new_todo(list_a):
    output=[]
    for i in list_a:
        tmp={}
        tmp['id']=gen_id()
        tmp['content']=i
        tmp['stat']='unprocessed'
        output.append(tmp)
    return output

#func that return response to user
# def response():

#func that check new or udpated to do list in memory
# def get_todo_update():

#func that give the next review date of todolist,give todo id if not available,and mapping  between todo to eventid
# def next_review():

#structure of the todo data
# {
# 'todo_id':'random'
# 'event_id_in':[]
# 'event_id_out':[]#these are the passed event
# 'review_date':'2025-03-04' # next date that it needs to be updated, usully every saturday
# 'priority':'1-5'
# 'description':'Every 2 days, timeslot 16:00-17:00 (adjusted dynamically)'
# 'category':''
# 'status':''

# }


#func that return the recent month event since current date    
# def get_recent_month():

#this function will use period event info and extend to multiple json format
# def extend():


