#this is the code for this schedule system
import os
import json
import asyncio
import websockets
from datetime import datetime, timedelta 
from tools import *
from pymongo import MongoClient
from openai import OpenAI

############################trigger one:user demand

#the workflow could be 
# 1.listening 
# 2.get user input ,start dialouge 
# 3.excurte 
# 4.stop and wait 5 minutes 
# 5. save dialouge to memory, clear memory and hault the program

DEEPSEEK_API_KEY = 'sk-c3b547b62c224059ba0cebfafc7a4f0a'
DEEPSEEK_URL = "https://api.deepseek.com"
client = OpenAI(api_key=DEEPSEEK_API_KEY,base_url=DEEPSEEK_URL)

#get the response of llm and add a name to it
def llm_invoke(client, llm_name, prompt, agenttype):
    messages = [prompt[0]]
    for msg in prompt[1:]:
        messages.append({"role":msg[0],"content":msg[1]})
    response = client.chat.completions.create(
        model = llm_name,
        messages = messages,
        stream = False
    )
    return f"[{agenttype}]: {response.choices[0].message.content}"

def pack_non_schedule(non_schedule: str)->str:
    pack_json = {
        'data': non_schedule,
        'state': 'non_schedule'
    }
    return json.dumps(pack_json)

def pack_schedule(schedule: str,type: str)->str:
    pack_json = {
        'data': schedule,
        'state': 'schedule',
        'type': type,
        'datatype': ''
    }
    return json.dumps(pack_json)

def pack_period_schedule(schedule: str,type: str,datatype: str)->str:
    pack_json = {
        'data': schedule,
        'state': 'schedule',
        'type': type,
        'datatype': datatype
    }
    return json.dumps(pack_json)

async def chat_plan(websocket):
    global time 
    global feteched_data
    global user_input
    global new_data
    #get the current time
    time = datetime.now().strftime("%Y-%m-%d %H:%M")
    #start dialougue
    #floor messages does not have agent syspromt
    floor_messages = []
    #get user's input
    await websocket.send(pack_non_schedule("Hello, I am your personal time planning assistant DPlanner. Do you have anything to arrange?"))
    while(True):
        user_input = await websocket.recv()
    
        #router
        router_msg=chater_prompt()
        router_msg.append(("user",user_input))
        response=llm_invoke(client, "deepseek-chat", router_msg, "chater")
        action = response.lower().split("user needs:")[1].strip()
    

        #add
        if action=='add':
            #call extractor
            add_msg=add_extractor_prompt()
            add_msg.append(("user",user_input))
            response = llm_invoke(client, "deepseek-chat", add_msg, "add_extractor")
            # 测试
            # await websocket.send(pack_non_schedule(response))
            add_msg.append(("assistant",response))
            if "turns:1" in response and "Status:completed" in response:
                #check the conflict
                new_data=json.loads(response.lower().split("collected events:")[1].strip())
                feteched_data = get_add_event(new_data)
                check_conflict = check_time_conflicts(feteched_data,new_data)
                if len(check_conflict)>0:
                    conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
                    add_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
                    #report conflict
                    await websocket.send(pack_non_schedule(conflict_output))
                    #wait user's input
                    #use the preference to solve the conflict
                    user_input = await websocket.recv()
                    router_msg.append(("user",user_input))
                    conflict_action = llm_invoke(client, "deepseek-chat", router_msg, "chater")
                    #if cancel, end the dialogue
                    if "delete" in conflict_action:
                        floor_messages.append(add_msg[1:])
                        await websocket.send(pack_non_schedule("The arrangement has been cancelled!"))
                        continue
                        # return "user delete the new events"
                    else:
                        #send it to add planner
                        addplan_msg = add_planner_prompt()
                        addplan_msg.append(("user",user_input))
                        confirm_stat = False # has to be confirmed by user
                        while not confirm_stat:
                            response = llm_invoke(client, "deepseek-chat", addplan_msg, "add_planner")
                            addplan_msg.append(("assistant",response))
                            try:
                                conflict_res = response.lower().split("conflict explanation:")[1].split("----separate line----")[0].strip()
                                await websocket.send(pack_non_schedule(conflict_res))
                                user_input = await websocket.recv()
                                addplan_msg.append(("user",user_input))
                            except:
                                solved_plan= response.lower().split("Suggested Schedule")[1].split("----separate line----")[0].strip()
                                await websocket.send(pack_non_schedule("OK! conflict solved \n"+solved_plan+"\n Would you confirm?"))
                                user_input = await websocket.recv()
                                addplan_msg.append(("user",user_input))
                                confirm_msg = confirm_agent_prompt()
                                confirm_msg.append(("user",user_input))
                                get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                                if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                                    confirm_stat=True
                                # disagree?
                try:
                    final_schedule = json.loads(response.lower().split("suggested Schedule:")[1].split("----separate line----")[0].strip())
                except:
                    final_schedule = new_data
                #send final schedule back to frontend
                #await websocket.send(pack_non_schedule(json.dumps(new_data)))
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                write_event(final_schedule)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                #need to delete the event in the new event listed first
                floor_messages.append(add_msg[1:])
                floor_messages.append(addplan_msg[1:])
                continue
                # return "new event has been added"
            else:
                await websocket.send(pack_non_schedule(extract_message(response.lower(),"grounded message:"))) # ask for more infor 
                user_input = await websocket.recv()
                add_msg.append(("user",user_input))
                response = llm_invoke(client, "deepseek-chat", add_msg, "add_extractor")
                add_msg.append(("assistant",response))
                # still partially completed?

            if "turns:2" in response and "Status:completed" in  response: #similar to round 1
                new_data=json.loads(response.lower().split("collected events:")[1].strip())
                feteched_data =get_add_event(new_data)
                check_conflict = check_time_conflicts(feteched_data,new_data)
                if len (check_conflict)>0:
                    conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
                    add_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
                    #report conflict
                    await websocket.send(pack_non_schedule(conflict_output))
                    #wait user's input
                    #use the preference to solve the conflict
                    user_input = await websocket.recv()
                    router_msg.append(("user",user_input))
                    conflict_action = llm_invoke(client, "deepseek-chat", router_msg, "chater")
                    #if cancel, end the dialogue
                    if "delete" in conflict_action:
                        floor_messages.append(add_msg[1:])
                        await websocket.send(pack_non_schedule("The arrangement has been cancelled!"))
                        continue
                        # return "user delete the new events"
                    else:
                        #send it to add planner
                        addplan_msg = add_planner_prompt()
                        addplan_msg.append(("user",user_input))
                        confirm_stat = False # has to be confirmed by user
                        while not confirm_stat:
                            response = llm_invoke(client, "deepseek-chat", addplan_msg, "add_planner")
                            addplan_msg.append(("assistant",response))
                            try:
                                conflict_res = response.lower().split("conflict explanation:")[1].split("----separate line----")[0].strip()
                                await websocket.send(pack_non_schedule(conflict_res))
                                user_input = await websocket.recv()
                                addplan_msg.append(("user",user_input))
                            except:
                                solved_plan= response.lower().split("Suggested Schedule")[1].split("----separate line----")[0].strip()
                                await websocket.send(pack_non_schedule("OK! conflict solved \n"+solved_plan+"\n Would you confirm?"))
                                user_input = await websocket.recv()
                                addplan_msg.append(("user",user_input))
                                confirm_msg = confirm_agent_prompt()
                                confirm_msg.append(("user",user_input))
                                get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                                if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                                    confirm_stat=True
                                # disagree?
                try:
                    final_schedule = json.loads(response.lower().split("suggested Schedule:")[1].split("----separate line----")[0].strip())
                except:
                    final_schedule = new_data
                #send final schedule back to frontend
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                write_event(final_schedule)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                #need to delete the event in the new event listed first
                floor_messages.append(add_msg[1:])
                floor_messages.append(addplan_msg[1:])
                continue
                # return "new event has been added"
            else: 
                #information is not enough , call add planner
                #planner need new data, and fetched data 
                new_data = json.loads(response.lower().split("collected events:")[1].strip())
                feteched_data = get_add_event(new_data)
                user_input = None# now user does not have feedback yet
                addplan_msg = add_planner_prompt()
                conflict_res = []
        
                confirm_stat = False # has to be confirmed by user 
                while not confirm_stat:
                    response = llm_invoke(client, "deepseek-chat", addplan_msg, "add_planner")
                    addplan_msg.append(("assistant",response))
                    try:
                        conflict_res = response.lower().split("conflict explanation:")[1].split("----separate line----")[0].strip()
                        addplan_msg.append(("assistant",f'[conflict checker]: {conflict_res}'))
                        await websocket.send(pack_non_schedule(conflict_res))
                        user_input = await websocket.recv()
                        addplan_msg.append(("user",user_input))
                        confirm_msg= confirm_agent_prompt()
                        confirm_msg.append(("user",user_input))
                        get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                        if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                            confirm_stat=True
                    except:    
                        if(len(conflict_res))==0:
                            # never have conflict
                            solved_plan= response.lower().split("suggested schedule:")[1].split("----separate line----")[0].strip()
                            await websocket.send(pack_non_schedule("OK!\n"+solved_plan+"\n Would you confirm?"))
                            user_input = await websocket.recv()
                            addplan_msg.append(("user",user_input))
                            confirm_msg= confirm_agent_prompt()
                            confirm_msg.append(("user",user_input))
                            get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                            if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                                confirm_stat=True
                        else:
                            #conflict has been solved
                            solved_plan= response.lower().split("suggested schedule:")[1].split("----separate line----")[0].strip()
                            await websocket.send(pack_non_schedule("OK! conflict solved \n"+solved_plan+"\n Would you confirm?"))
                            user_input = await websocket.recv()
                            addplan_msg.append(("user",user_input))
                            confirm_msg=confirm_agent_prompt()
                            confirm_msg.append(("user",user_input))
                            get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                            if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                                confirm_stat=True

                final_schedule=json.loads(response.lower().split("suggested schedule:")[1].split("----separate line----")[0].strip())
                #send final schedule back to frontend
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                write_event(final_schedule)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                try:
                    cancel_events = json.loads(response.lower().split("cancel list:")[1].split("----separate line----")[0].strip())
                    delete_event(cancel_events)
                except ValueError:
                    pass
                
            #add all messages to floor at last
            #the first one is the system prompt, do not add to floor
            floor_messages.append(add_msg[1:])
            floor_messages.append(addplan_msg[1:])
            # return "new event has been added"


    
        #period
        if action=='period':
        #front end should return a dict{new:,delete:}    
            new_todo = get_new_todo([user_input])
            #await websocket.send(pack_non_schedule(json.dumps(new_todo)))
            #get existed event of recent month
            cur_date = time+"  "+ datetime.strptime(time, "%Y-%m-%d %H:%M").strftime("%A")
            feteched_data = get_recent_events(time,30)
            global return_feedback
            return_feedback = None # intitial has no feedback
            for item in new_todo:
                format_input=f'''
                "existed":{feteched_data},
                "user demand":{item['content']}
                "preference":"I don't want to do some sports at weekends."
                '''
                todo_planner=todo_planner_prompt(cur_date)
                todo_planner.append(('user',format_input))
                confirm_stat=False
                while not confirm_stat:
                    response = llm_invoke(client, "deepseek-reasoner", todo_planner, "todo_planner")
                    #await websocket.send(pack_non_schedule(response))
                    todo_planner.append(("assistant",response))
                    plan_details=response.lower().split("current date:")[0]+"do you agree with this plan?"
                    await websocket.send(pack_non_schedule(plan_details))
                    user_input = await websocket.recv()
                    todo_planner.append(("user",user_input))
                    confirm_msg=confirm_agent_prompt()
                    confirm_msg.append(("user",user_input))
                    get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                    if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                        confirm_stat=True
                
                attribute=response.lower().split("event attribute:")[1].split("start date:")[0].strip()
                #await websocket.send(pack_non_schedule(attribute))
                time_slot=response.lower().split("adjusted time slot details for each recurred event:")[1].split("current date:")[0].strip()
                #await websocket.send(pack_non_schedule(time_slot))
                event_list=get_extend(attribute,time_slot)
                #await websocket.send(pack_non_schedule(json.dumps(event_list)))
                #write to event list
                await websocket.send(pack_period_schedule(json.dumps(event_list),'period','calendar'))
                write_event(event_list)
                #update the review time of todo
                item['origin_plan']=response.lower().split("recurring time slot:")[1].split("adjusted time slot details for each recurred event:")[0].strip()
                last_event_time = datetime.strptime(event_list[-1]['end_time'], "%Y-%m-%d %H:%M")
                item['review_time'] = last_event_time.strftime("%Y-%m-%d") # when the last planned event is complete, review 
                item['stat']='processed'
                #add binned eventid
                item['binned_event']= [event['event_id'] for event in event_list]
                
                
            # if delete_todo:
            #     for item in delete_todo:
            #         delete_event(item['binned_event'])
            #         item['stat']='deleted'
            #         item['binned_event']=[]
    
            # update todo list
            # for item in delete_todo:
            #         for i, stored_item in enumerate(stored_todo):
            #             if stored_item['id'] == item['id']:
            #                 stored_todo[i] = item
            #                 break
                
            # add new todos
            # stored_todo.extend(new_todo)
            await websocket.send(pack_period_schedule(json.dumps(new_todo),'period','todolist'))
            await websocket.send(pack_non_schedule("The arrangement has been finished!"))

        #could update the datebase here 
    # period
    # if action=='review':
    #     cur_date= time+"  "+ datetime.strptime(time, "%Y-%m-%d %H:%M").strftime("%A")
    #     cur_day= datetime.strptime(time, "%Y-%m-%d %H:%M").strftime("%Y-%m-%d")
    #     review_list=[i for item in stored_todo if item['stat']=='processed' and item['review_time']==cur_day]

    #     for item in review_list:
    #         feteched_data =get_recent_events(time,30)
    #         return_feedback=item['origin_plan'] # use origin plan as feedback
    #         format_input=f'''
    #         "existed":{feteched_data},
    #         "user demand":{item['content']}
    #         '''
    #         # during reviewing, these is not need to ask for confirm
    #         todo_planner=todo_planner_prompt(cur_date)
    #         response = type_agent("todo_planner",todo_planner,llm2)
    #         todo_planner.append(("assistant",response))

    #         attribute=response.lower().split("event attribute:")[1].split("start date:")[0].strip()
    #         time_slot=response.lower().split("adjusted time slot details for each recurred event:")[1].split("current date:")[0].strip()
    #         event_list=get_extend(attribute,time_slot)
    #         #write to event list
    #         write_event(event_list)
    #         #update the review time of todo
    #         last_event_time = datetime.strptime(event_list[-1]['end_time'], "%Y-%m-%d %H:%M")
    #         item['review_time'] = last_event_time.strftime("%Y-%m-%d") # when the last planned event is complete, review 
    #         #add binned eventid, the old eventid is removed 
    #         item['binned_event']= [event['event_id'] for event in event_list]




    #check
    # if action=='check':
        #check the schedule for a specific time
        # check_msg=check_prompt()
        # check_msg.append(("user",user_input))
        # response = type_agent("check",check_msg,llm)
        # check_msg.append(("assistant",response))



#end of dialogue, when no one speak for 5 mins

#save the dialogue to memory

########################trigger two:system clock

#event notice clock

#period event plan clock

#summary and analysis clock



def confirm_agent_prompt():
    return [{"role":"system","content":f"""
role:
you are a sensitive agent that good at judging the user's agreement to the plan.

output:
if the user agree, return "agree"
if the user disagree, return "disagree"
if the user is using a statement, not showing any intention, return "none"

this is user input:{user_input}
"""}]

def chater_prompt():
    return [{"role":"system","content":f'''

Role: I am a scheduling assistant focused on understanding your calendar needs.

My task is to identify if you want to:
1. Add a new event
2. Check existing schedule
3. Modify an event
4. delete an event
5. Add a periodic event

The period phrase could be like this (could be more than this):
"Every week" 
"Every 10 days" 
"Twice a month" 
"every Mon/Wed/Fri"



Output:
I will respond with "User needs: (add/check/modify/delete/period)" followed by relevant questions.
no other words are allowed

Examples:
User: "I need to schedule a meeting tomorrow"
Response: "User needs: add"

User: "What's on my calendar for next week?"
Response: "User needs: check"

User: "Can you change the time of my dentist appointment?"
Response: "User needs: modify"
'''}]

def add_extractor_prompt():
    return [{"role":"system","content":f"""
Role: I am an event information collector. I will:

1. Extract event details from user message in this event format:
when implicite time give(e.g. tommorow), you may use current time{time} to infer.
Do not hallucinate if the information is not given in users response.
If information is not provided in user message, the corresponding item should not existed.
Auto-infer and fill category item only (Work/Personal/Health).
You should auto gen an eventid over 20 digits that impossible to repeat
{{
    "event_id": "random_alphanumeric", 
    "start_time": "YYYY-MM-DD HH:MM", 
    "end_time": "YYYY-MM-DD HH:MM",   
    "category": "Work/Personal/Health",
    "description": "user input",
    "priority": "1-5"
}}

2.Missing field identify:
Compare your extracted information json to the event format (fields include start_time,end_time,category,description, priority), identify which fields are missing


3. Grounding process:
If identify missing information,you need to aks user to provided it by: "Would you provide more information about [list missing fields]?"

After user reply,use user reply to update the extracted information, then decide :
(1)if every filed is complete, reply :"Ok, I shall help you arrange it"
(2)if every filed is not complete, reply "Since you haven't given all info, I shall try it based on your preference"

Rule:
1.Only update the extracted information with the information user provided(except category could be infer by you ), do not infer and add to the field.


4. Output format:
1.turns:1-2(this is showing the number of turns that you are anwsering)
2.Reasoning:(the reason process how you get the final collected events)
3.Status: completed/partially completed
4.grounded message: "your grounded message"
5.Collected events: list of newly scheduled events [{{}},{{}}]

output rules:
1.YOU MUST STRICTLY FOLLOW THE OUTPUT FORMAT
2.DO NOT ADD WORDS BEFORE OR AFTER THE 4 OUPUTPARTS
3.Do not add space after ":", (turns:1 is valid)(turns: 1 is invalid)

Valid format example:
turns:1
Status:completed
grounded message:would you provide more information about end_time?
Collected events:[{{"event_id":"123456789012345678901","start_time":"2024-02-26 14:00","end_time":"2024-02-26 15:00","description":"meeting","priority":"5"}}]

invalid format example:
Collected events:[{{"event_id":"123456789012345678901","start_time":"2024-02-26 14:00","end_time":"2024-02-26 15:00","description":"meeting","priority":"5"}}] tell me if you need more help

5.Rules:
1.At most you can response two times, first time the turns=1, second time the turns=2
2.After first response, no matter user provide more information or not, you should not repeat ask for more information.

"""}]

def add_planner_prompt():
    return [{"role":"system","content":f"""Role: I am a Schedule Planning Specialist that optimizes event scheduling.
    I need to follow the rules and the output format strictly. 
    I need to consider user preference.

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
YOU MUST FOLLOW THIS EXACT FORMAT WITHOUT ANY DEVIATION:
IMPORTANT FORMATTING RULES:
1. Do not include any markdown formatting (no ```, no indentation)
2. The JSON must be valid and properly formatted
Suggested Schedule:
[
    {{
        "event_id": "value",
        "start_time": "value",
        "end_time": "value",
        "category": "value",
        "description": "value",
        "priority": "value"
    }}
]
----separate line----
Conflict explanation: (only include if conflicts exist)
Only explain why you give the suggestion when you found conflict, and only explain about the conflict using event names or descriptions,
do not use event id ,do not include others.
----separate line----
Cancel list: (only include if user want to cancel events)
same format as  Suggested Schedule
----separate line----
Would this schedule work for you?

Your input is listed here:
existed_events:{feteched_data}, 
new_requirement:{new_data},
user preference:{user_input}

rules:
1.if no conflict found, do not explain conflict in the output.
2.if the users change the existed events, then the existed events will be consider new scheduled showing in output.
3.if found conflict, you should use your knowledge to adjust the new_requirement or existed_events.
4.in the Suggested Schedule, only show new add event or the existed event that is adjusted by you.
5.if the user cancel the existed events,show the cancel events in canel list

"""}]


def todo_planner_prompt(cur_date):
    return [{"role":"system","content":f'''
Role: 
You are an AI schedule agent expert in intelligently inserting recurring events into a user's 
calendar through holistic time optimization and human-centric reasoning.

Objective:
Find the earliest possible start date and optimal recurring  time slot for the user’s requested event that:
Avoids conflicts with existing events.
Follows natural activity sequences (e.g., n o sports after sports, buffer before critical meetings).
Respects time preferences (e.g., no early-morning sports).
Aligns with event duration norms (e.g., workouts = 45–90 mins).
Schecule for the next 30 days since the start date

Rules:
Start Date Calculation
If the user specifies a timeframe (e.g., “starting next week”), calculate the first valid day:
example( if current date is Saturday, then next week should be next monday)
If unspecified, start on the earliest conflict-free day.

Period Handling:
User Phrase → Period Definition:
"Every week" → Schedule 1 event within each 7-day window (days can vary).
"Every 10 days" → Schedule 1 event every 10-day interval (days can vary).
"Twice a month" → Schedule 2 events, each in separate 15-day windows.
Custom patterns (e.g., "every Mon/Wed/Fri") still apply if explicitly stated.
Flexible Day Selection：
For each period, dynamically select any day
If multiple days are valid, prioritize the most suitable day based on user preferences,prefer the same weekday if possible.
Try to balance the numers of events in each period, for example (do not put everything on monday if other days are so free).


Time Slot Selection(Apply to Every Occurrence)
Prioritization Logic:
Assign desire time slot to high priority events.
First check the most preferred time slot for an event, it does not need to follow the existed event closly.
Consider enough time break between two consecutive quite different events, because extra time is needed to change location or prepare for the next event.
Sequence Logic:
Buffer 60+ mins before high-priority meetings.
Separate similar activities (e.g., gym → meeting → yoga, not gym → yoga).
Natural Timing:
Creative work: 8:00–11:00 AM.
Exercise: 9:00 AM – 10:00 AM and 16:00PM - 20:00PM.
Meetings: 9:00 AM – 5:00 PM.
Auto-Assign Attributes
Duration: Assign based on event type (e.g., workout = 60 mins, meeting = 30 mins).
Split a very long duration if is not explicitly a continuous event, the split ones could flexibly select days and time slot trying to balance.
Priority: Default to medium unless stated (e.g., “urgent” = high).
The time slot could be different for each occurence if needed.


User preference(you must follow this preference):
Avoid Early Morning Sports: No intense activities (gym, swim) before 9:00 AM.
Do not plan two sports event in the same day.
{return_feedback}

Conflict Resolution
If no slots fit, propose alternatives (e.g., shorten duration, adjust days) with explanations.

**In the output:
you need to show the final proposed schedule after the dynamic adjustments, strickly follow this format:
FOLLOW THIS FORMAT! THE TITLE OF EACH LINE SHOULD EXACTLY SAME AS THE FORMAT GIVEN
TIME SLOT IS PRESENTED IN 24hour format (2025-04-02,13:00-21:00)
FOLLOW THE SAME SEQUENCE of the title of each line

event attribute:priority:1-5,category:,description:
start date:date
recurring time slot:period description(e.g. everyday), timeslot (e.g. 15:00-16:00)
adjusted time slot details for each recurred event: a list [date, time slot]
current date: {cur_date}


example:
adjusted time slot details for each recurred event:(this is valid)
adjusted time slot details:(this is not valid)

'''}]

async def delete(websocket):
    # delete relevant events in database

    return 0

async def handler(websocket):
    """handle each WebSocket connection"""
    goal = await websocket.recv()
    if goal == 'chat_plan':
        await chat_plan(websocket)
    elif goal == 'delete':
        await delete(websocket)

async def main():
    port = int(os.getenv("PORT", 80))
    async with websockets.serve(
        handler,
        host="0.0.0.0",
        port=port,
        ping_interval=5,
        ping_timeout=10,
        close_timeout=3600
    ):
        print(f"服务已启动，监听端口 {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
