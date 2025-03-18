#this is the code for this schedule system
#from sysprompt import get_prompt

#write event list to mongodb
from pymongo import MongoClient
import json
from datetime import datetime, timedelta 
import getpass
import os
from langchain_deepseek import ChatDeepSeek
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def from_frontend():
    user_input = request.json.get('content')
    # if not user_input:
    #     return jsonify({"code":400, "error":"Empty message"}), 400
    return user_input

@ app.route('/chat', methods=['POST'])
def to_frontend(text):
    return jsonify({"code":200, "reply":text})

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=5000,
    timeout=30,
    max_retries=2,
    api_key="sk-dba351629c004c41b3c4c99c9e806db4"
    # other params...
)

def confirm_agent_prompt():
    return f"""
role:
you are a sensitive agent that good at judging the user's agreement to the plan.

output:
if the user agree, return "agree"
if the user disagree, return "disagree"
if the user is using a statement, not showing any intention, return "none"

this is user input:{user_input}
"""

def chater_prompt():
    return f'''

Role: I am a scheduling assistant focused on understanding your calendar needs.

My task is to identify if you want to:
1. Add a new event
2. Check existing schedule
3. Modify an event
4. delete an event
 
Output:
I will respond with "User needs: (add/check/modify/delete)" followed by relevant questions.
no other words are allowed

Examples:
User: "I need to schedule a meeting tomorrow"
Response: "User needs: add"

User: "What's on my calendar for next week?"
Response: "User needs: check"

User: "Can you change the time of my dentist appointment?"
Response: "User needs: modify"
'''

def add_extractor_prompt():
    return f"""
Role: I am an event information collector. I will:

1. Extract event details from user message in this format:
when implicite time give(e.g. tommorow), you may use current time{time} to infer.
Do not hallucinate if the information is not given in users response.
Auto-infer category (Work/Personal/Health).
You should auto gen an eventid over 20 digits that impossible to repeat
{{
    "event_id": "random_alphanumeric", 
    "start_time": "YYYY-MM-DD HH:MM", (required)
    "end_time": "YYYY-MM-DD HH:MM",   
    "category": "Work/Personal/Health",
    "description": "user input",
    "priority": "1-5"
}}

2. 
grounded message: "your grounded message"
when fields are missing from user statement (fields include start_time,end_time,category,description, priority):
- First Response: respond with "Would you provide more information about [list missing fields]?"
- Second Response: "Since you haven't given all info, I shall try it based on your preference"

When all fields provided: "Ok, I shall help you arrange it"

If any field is missing, you may ground "would you provide more information about (missing fileds) ?" Do not infer.
If  all field is provided, you may ground "ok i shall help you arrange it ". Do not infer.
If after your inquire the fields are still missing , you may ground "since you haven't give all info, i shall try it based on your preference " .In this case, the status should be partially completed.


3. Output format:
turns:1-2(this is showing the number of turns that you are anwsering)
Status: completed/partially completed
grounded message: "your grounded message"
Collected events: list of newly scheduled events


Example:
User: "Schedule a meeting tomorrow at 2pm"
Response: "I need the following details:
- Meeting duration/end time
- Priority (1-5)
- Category (Work/Personal/Health)

Status: partially completed
Events: [{{
    "event_id": "mt123xyz",
    "start_time": "2025-02-26 14:00",
    "description": "meeting"
}}]
"""

def add_planner_prompt():
    return f"""Role: I am a Schedule Planning Specialist that optimizes event scheduling.
    I need to follow the rules and the output format strictly.

Input:
- Existing Events: Current scheduled events list
- New Requirements: Events to be scheduled (may have missing fields)
- User Preferences: Optional scheduling preferences

Process:
1. For incomplete events, I will:
   - Set default meeting duration: 1 hour
   - Assign appropriate priority (1-5)
   - Consider category-based optimal timing

2. For scheduling, I will:
   - Avoid time conflicts,Avoid time conflicts
   - Follow scheduling best practices
   - Consider event categories and priorities

Output Format:
(follow this sequence)
1.Suggested Schedule:
2.----separate line----(make sure always output this line)
3.Conflict explaination:(optional when there is no conflict)
4.would this work for you?

Suggested Schedule:
(below should be a list of new scheduled event [{{}},{{}}])
{{
    "event_id": [original],
    "start_time": [original or suggested],
    "end_time": [original or suggested],
    "category": [original],
    "description": [original],
    "priority": [original or suggested]
}}


Would this schedule work for you?"

Conflict explaination:
Only explain why you give the suggestion when you found conflict, and only explain about the conflict using event names or descriptions,
do not use event id ,do not include others.

After user feedback:
- If changes needed: Provide new suggestion
- If confirmed: Output final format:
status: confirmed
plan: a list final schedule details [{{}},{{}}]

Your input is listed here:
existed_events:{feteched_data}, 
new_requirement:{new_data},
 user preference:{user_input}

rules:
1.if no conflict found, do not explain conflict in the output.
2.if the users change the existed events, then the existed events will be consider new scheduled showing in output.
3.if found conflict, you should use your knowledge to adjust the new_requirement or existed_events.
4.in the Suggested Schedule, only show new add event or the existed event that is adjusted by you.

"""

#check Conflict 
from datetime import datetime
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

# add a name to the response of llm 
def type_agent(agenttype,message,llm):
    response = llm.invoke(message)
    return f"[{agenttype}]: {response.content}"



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

def from_frontend():
    return input("please enter: ")


#extract part from the llm response
def extract_message(response, field):
    # Find the grounded message between quotes
    if field in response:
        # Split by grounded message: and get the part after it
        message_part = response.split("grounded message:")[1].strip()
        # Extract content between quotes
        try:
            message = message_part.split('"')[1]
            return message
        except IndexError:
            return None
    return None


def from_frontend():
    return input("please enter: ")

def to_frontend(text):
    print(text)
#the workflow could be 
# 1.listening 
# 2.get user input ,start dialouge 
# 3.excurte 
# 4.stop and wait 5 minutes 
# 5. save dialouge to memory, clear memory and hault the program




user_input='i will swim tommorow at 10 am,20250303,1 hour'
#start dialougue
floor_messages=[]
#user input
user_input = from_frontend()
#floor messages does not have agent syspromt
floor_messages.append(("user",user_input))

#router
router_msg=chater_prompt()
router_msg.append(("user",user_input))
response = type_agent("chater",router_msg,llm)

action = response.split("User needs:")[1].strip()

#add
if action=='add':
    #call extractor
    add_msg=add_extractor_prompt()
    add_msg.append(("user",user_input))
    response = type_agent("add_extractor",add_msg,llm)
    add_msg.append(("assistant",response))
    if "turns: 1" in response and "Status: completed" in  response:
        new_data=json.loads(response.split("Collected events:")[1].strip())
        feteched_data =get_add_event(new_data)
       # new_data =json.loads(response.split("```json")[1].strip().split("```")[0].strip())
        check_conflict = check_time_conflicts(feteched_data,new_data)
        if len(check_conflict)>0:
            conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
            add_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
            to_frontend(conflict_output) # report conflict
            user_input = from_frontend()
            add_msg.append(("user",user_input))
            router_msg.append(("user",user_input)) # this will check what user want to do with the conflict
            conflict_action = type_agent("chater",router_msg,llm)
            #if cancel, end the dialogue
            if "delete" in conflict_action:
                floor_messages.append(add_msg[1:])
                print("user delete the new events")
            else:
                #send it to add planner
                addplan_msg=add_planner_prompt()
                get_confirm=False # has to be confirmed by user 
                while not get_confirm:
                    response = type_agent("add_planner",addplan_msg,llm)
                    addplan_msg.append(("assistant",response))
                    try:
                        conflict_res= response.split("Conflict explanation:")[1].split("Would this")[0].strip()
                        to_frontend(conflict_res)
                        user_input = from_frontend()
                        addplan_msg.append(("user",user_input))
                    except:    
                        solved_plan= response.split("Suggested Schedule")[1].split("----separate line----")[0].strip()
                        to_frontend("OK! conflict solved \n"+solved_plan+"\n Would you confirm?")
                        user_input = from_frontend()
                        addplan_msg.append(("user",user_input))
                        confirm_msg=confirm_agent_prompt()
                        get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                        if get_confirm.split('[confirm_agent]:')[1].strip()=="agree":
                            get_confirm=True

                final_schedule=json.loads(response.split("Suggested Schedule:")[1].split("----separate line----")[0].strip())
                write_event(final_schedule)#need to delete the event in the new event listed first
                floor_messages.append(add_msg[1:])
                floor_messages.append(addplan_msg[1:])
                print("new event has been added")
    else:
        to_frontend(extract_message(response,"grounded message:")) # ask for more infor 
        user_input = from_frontend()
        add_msg.append(("user",user_input))
        response = type_agent("add_extractor",add_msg,llm)
        add_msg.append(("assistant",response))

    if "turns:2" in response and "status:completed" in  response: #similar to round 1
        new_data=json.loads(response.split("Collected events:")[1].strip())
        feteched_data =get_add_event(new_data)
       # planned_event =json.loads(response.split("```json")[1].strip().split("```")[0].strip())
        check_conflict = check_time_conflicts(feteched_data,new_data)
        if len (check_conflict)>0:
            conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
            add_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
            to_frontend(conflict_output) # report conflict
            user_input = from_frontend()
            add_msg.append(("user",user_input))
            router_msg.append(("user",user_input)) # this will check what user want to do with the conflict
            conflict_action = type_agent("chater",router_msg,llm)
            #if cancel, end the dialogue
            if "delete" in conflict_action:
                floor_messages.append(add_msg[1:])
                print("user delete the new events")
            else:
                #send it to add planner
                addplan_msg=add_planner_prompt()
                get_confirm=False # has to be confirmed by user 
                while not get_confirm:
                    response = type_agent("add_planner",addplan_msg,llm)
                    addplan_msg.append(("assistant",response))
                    try:
                        conflict_res= response.split("Conflict explanation:")[1].split("Would this")[0].strip()
                        to_frontend(conflict_res)
                        
                        user_input = from_frontend()
                        addplan_msg.append(("user",user_input))
                    except:    
                        solved_plan= response.split("Suggested Schedule")[1].split("----separate line----")[0].strip()
                        to_frontend("OK! conflict solved \n"+solved_plan+"\n Would you confirm?")
                        user_input = from_frontend()
                        addplan_msg.append(("user",user_input))
                        confirm_msg=confirm_agent_prompt
                        get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                        if get_confirm.split('[confirm_agent]:')[1].strip()=="agree":
                            get_confirm=True

                final_schedule=json.loads(response.split("Suggested Schedule:")[1].split("----separate line----")[0].strip())
                write_event(final_schedule)#need to delete the event in the new event listed first
                floor_messages.append(add_msg[1:])
                floor_messages.append(addplan_msg[1:])
                print("new event has been added")

    else: # information is not enough , call add planner
        #planner need new_data, and fetched data 
       # new_data =json.loads(response.split("```json")[1].strip().split("```")[0].strip())
        new_data=json.loads(response.split("Collected events:")[1].strip())
        feteched_data =get_add_event(new_data)
        user_input=None# now user does not have feedback yet
        addplan_msg=add_planner_prompt()

        get_confirm=False # has to be confirmed by user 
        while not get_confirm:
            response = type_agent("add_planner",addplan_msg,llm)
            addplan_msg.append(("assistant",response))
            try:
                conflict_res= response.split("Conflict explanation:")[1].split("Would this")[0].strip()
                addplan_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
                to_frontend(conflict_res)
                user_input = from_frontend()
                addplan_msg.append(("user",user_input))
                confirm_msg= confirm_agent_prompt()
                get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                if get_confirm.split('[confirm_agent]:')[1].strip()=="agree":
                    get_confirm=True
            except:    
                if(len(conflict_res))==0:
                    # never have conflict
                    solved_plan= response.split("Suggested Schedule")[1].split("Would this")[0].strip()
                    to_frontend("OK! Here is the suggested schedule \n"+solved_plan+"\n Would you confirm?")
                    user_input = from_frontend()
                    addplan_msg=addplan_msg.append(("user",user_input))
                    confirm_msg= confirm_agent_prompt()
                    get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                    if get_confirm.split('[confirm_agent]:')[1].strip()=="agree":
                        get_confirm=True
                else:
                    #conflict has solved
                    solved_plan= response.split("Suggested Schedule")[1].split("Would this")[0].strip()
                    to_frontend("OK! conflict solved \n"+solved_plan+"\n Would you confirm?")
                    user_input = from_frontend()
                    addplan_msg.append(("user",user_input))
                    confirm_msg=confirm_agent_prompt
                    get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                    if get_confirm.split('[confirm_agent]:')[1].strip()=="agree":
                        get_confirm=True


        final_schedule=json.loads(response.split("Suggested Schedule:")[1].split("Would this")[0].strip())
        write_event(final_schedule)#need to delete the event in the new event listed first

#add all messages to floor at last
#the first one is the system prompt, do not add to floor
floor_messages.append(add_msg[1:])
floor_messages.append(addplan_msg[1:])
print("new event has been added")





#delete


#check



#modify




#end of dialogue, when no one speak for 5 mins

#save the dialogue to memory

########################trigger two:system clock


#event notice clock

#period event plan clock

#summary and analysis clock




SYSTEM_PROMPTS = {
    "chater": f'''

Role: I am a scheduling assistant focused on understanding your calendar needs.

My task is to identify if you want to:
1. Add a new event
2. Check existing schedule
3. Modify an event
4. delete an event
 
Output:
I will respond with "User needs: (add/check/modify/delete)" followed by relevant questions.
no other words are allowed

Examples:
User: "I need to schedule a meeting tomorrow"
Response: "User needs: add"

User: "What's on my calendar for next week?"
Response: "User needs: check"

User: "Can you change the time of my dentist appointment?"
Response: "User needs: modify"
'''
,


"add_extractor":f"""
Role: I am an event information collector. I will:

1. Extract event details from user message in this format:
when implicite time give(e.g. tommorow), you may use current time{time} to infer.
Do not hallucinate if the information is not given in users response.
Auto-infer category (Work/Personal/Health).
You should auto gen an eventid over 20 digits that impossible to repeat
{{
    "event_id": "random_alphanumeric", 
    "start_time": "YYYY-MM-DD HH:MM", (required)
    "end_time": "YYYY-MM-DD HH:MM",   
    "category": "Work/Personal/Health",
    "description": "user input",
    "priority": "1-5"
}}

2. 
grounded message: "your grounded message"
when fields are missing from user statement (fields include start_time,end_time,category,description, priority):
- First Response: respond with "Would you provide more information about [list missing fields]?"
- Second Response: "Since you haven't given all info, I shall try it based on your preference"

When all fields provided: "Ok, I shall help you arrange it"

If any field is missing, you may ground "would you provide more information about (missing fileds) ?" Do not infer.
If  all field is provided, you may ground "ok i shall help you arrange it ". Do not infer.
If after your inquire the fields are still missing , you may ground "since you haven't give all info, i shall try it based on your preference " .In this case, the status should be partially completed.


3. Output format:
turns:1-2(this is showing the number of turns that you are anwsering)
Status: completed/partially completed
grounded message: "your grounded message"
Collected events: list of newly scheduled events


Example:
User: "Schedule a meeting tomorrow at 2pm"
Response: "I need the following details:
- Meeting duration/end time
- Priority (1-5)
- Category (Work/Personal/Health)

Status: partially completed
Events: [{{
    "event_id": "mt123xyz",
    "start_time": "2025-02-26 14:00",
    "description": "meeting"
}}]
""",
"add_planner":f"""Role: I am a Schedule Planning Specialist that optimizes event scheduling.
    I need to follow the rules and the output format strictly.

Input:
- Existing Events: Current scheduled events list
- New Requirements: Events to be scheduled (may have missing fields)
- User Preferences: Optional scheduling preferences

Process:
1. For incomplete events, I will:
   - Set default meeting duration: 1 hour
   - Assign appropriate priority (1-5)
   - Consider category-based optimal timing

2. For scheduling, I will:
   - Avoid time conflicts,Avoid time conflicts
   - Follow scheduling best practices
   - Consider event categories and priorities

Output Format:
(follow this sequence)
1.Suggested Schedule:
2.----separate line----(make sure always output this line)
3.Conflict explaination:(optional when there is no conflict)
4.would this work for you?

Suggested Schedule:
(below should be a list of new scheduled event [{{}},{{}}])
{{
    "event_id": [original],
    "start_time": [original or suggested],
    "end_time": [original or suggested],
    "category": [original],
    "description": [original],
    "priority": [original or suggested]
}}


Would this schedule work for you?"

Conflict explaination:
Only explain why you give the suggestion when you found conflict, and only explain about the conflict using event names or descriptions,
do not use event id ,do not include others.

After user feedback:
- If changes needed: Provide new suggestion
- If confirmed: Output final format:
status: confirmed
plan: a list final schedule details [{{}},{{}}]

Your input is listed here:
existed_events:{feteched_data}, 
new_requirement:{new_data},
 user preference:{user_input}

rules:
1.if no conflict found, do not explain conflict in the output.
2.if the users change the existed events, then the existed events will be consider new scheduled showing in output.
3.if found conflict, you should use your knowledge to adjust the new_requirement or existed_events.
4.in the Suggested Schedule, only show new add event or the existed event that is adjusted by you.

""",
"confirm_agent":f"""
role:
you are a sensitive agent that good at judging the user's agreement to the plan.

output:
if the user agree, return "agree"
if the user disagree, return "disagree"
if the user is using a statement, not showing any intention, return "none"

this is user input:{user_input}
"""
}




user_input="ddd"
print(confirm_agent_prompt())
user_input='hhh'
print(confirm_agent_prompt())
user_input="aaa"
print(confirm_agent_prompt())