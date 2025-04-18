#this is the code for this schedule system
import re
import os
import json
import asyncio
import websockets
from datetime import datetime
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

def json_extract(response_content):
    pattern = r"```json(.*?)```"
    matches = re.findall(pattern, response_content, re.DOTALL)
    if matches:
        json_str = "\n".join(matches)
        return json.loads(json_str)
    else:
        raise ValueError(f"Response has problem in format!")

def qwen_llm(hist_messages, model_type, prompt):
    messages = [{'role': 'system', 'content': prompt}]
    messages.extend(hist_messages)
    
    completion = client.chat.completions.create(
        model=model_type,
        messages=messages
    )
    return completion.choices[0].message.content


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
    global preference_msg
    global start_time
    global extracted_hist
    #get the current time
    time = datetime.now().strftime("%Y-%m-%d %H:%M")
    #start dialougue
    #floor messages does not have agent syspromt
    floor_messages = []
    rf_db=prefereceDatabase()
    preference msg= list(rf_db.get by id (user_id))
    #get user's input
    await websocket.send(pack_non_schedule("Hello, I am your personal time planning assistant DPlanner. Do you have anything to arrange?"))
    while(True):
        user_input = await websocket.recv()
        #return from front end
        user_id='exampleid123'
        #router
        router_msg=[{'role':'user','content':user_input}]
        response = qwen_llm(router_msg,"qwen2.5-7b-instruct",chater_prompt()[0])
        action = response.lower().split("user needs:")[1].strip()
    

        #add
        if action=='add':
            #call extractor
            add_msg=[{'role':'user','content':user_input}]
            start_time= qwen_llm(add_msg,"qwen2.5-14b-instruct",time_infer_prompt()).split("Output:")[1].strip()
            await websocket.send(pack_non_schedule('start time '+start_time))
            extracted_hist=''
            extracted_hist=  qwen_llm(add_msg,"qwen2.5-32b-instruct",extracted_prompt())
            if "json" in extracted_hist:
                json_str= extracted_hist.split('json:')[1].strip()
            else :
                json_str=   extracted_hist
            json_data = json.loads(json_str)
            #missing_fields = extracted_hist.split('missing fields:')[1].strip().split('<list_end>')[0].strip()
            missing_fields = json_data["missing fields"]
            add_msg.append({'role':'assistant','content':extracted_hist})
            await websocket.send(pack_non_schedule('first extract'+extracted_hist))
            if len(missing_fields)<1:
                #check the conflict
                final_extracted=qwen_llm([{"role":"user","content":user_input}],"qwen2.5-32b-instruct",autofill_prompt())
                if "json" in final_extracted:

                    json_str = final_extracted.split('json:')[1].strip()
                else :
                    json_str=final_extracted
                new_data = json.loads(json_str)
                new_data = new_data['collected events']
                feteched_data =get_add_event(new_data)
            # new_data =json.loads(response.split("```json")[1].strip().split("```")[0].strip())
                check_conflict = check_time_conflicts(feteched_data,new_data)
                if len(check_conflict)>0:
                    conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
                    add_msg.append(("assistant",f'[conflict checker]: {conflict_output}'))
                    #report conflict
                    await websocket.send(pack_non_schedule(conflict_output))
                    #wait user's input
                    #use the preference to solve the conflict
                    user_input = await websocket.recv()
                    add_msg.append({"role":"user","content":user_input})
                    conflict_action = qwen_llm([add_msg[-1]],"qwen2.5-7b-instruct",chater_prompt()[0])
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
                            addplan_msg=[{'role':'user','content':user_input}]
                            response = qwen_llm(addplan_msg,"qwen2.5-32b-instruct",add_planner_prompt()[0])
                            if "json" in response:

                                json_str = response.split('json:').strip()
                            else :
                                json_str=response
                            json_data = json.loads(json_str)
                            addplan_msg.append({"role":"assistant","content":response})
                            try:
                                conflict_res = json_data['Conflict explanation']
                                await websocket.send(pack_non_schedule(conflict_res))
                                user_input = await websocket.recv()
                                addplan_msg.append({"role":"user","content":user_input})
                                get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                                if get_confirm == "agree":
                                    confirm_stat=True
                            except:
                                solved_plan=json_data["Suggested Schedule"]
                                await websocket.send(pack_non_schedule("OK! conflict solved \n"+str(solved_plan)+"\n Would you confirm?"))
                                user_input = await websocket.recv()
                                addplan_msg.append({"role":"user","content":user_input})
                                get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                                if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                                    confirm_stat=True
                                # disagree?
                try:
                    final_schedule=json_data["Suggested Schedule"]
                except:
                    final_schedule = new_data
                #send final schedule back to frontend
                #await websocket.send(pack_non_schedule(json.dumps(new_data)))
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                #write_event(final_schedule,user_id)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                #need to delete the event in the new event listed first
                floor_messages.append(add_msg)
                floor_messages.append(addplan_msg)
                continue
                # return "new event has been added"
            else:
                await websocket.send(pack_non_schedule("I am sorry, I could not find all the required information. Please provide the missing fields: "+str(missing_fields))) # ask for more infor 
                user_input = await websocket.recv()
                add_msg.append({"role":"user","content":user_input} )
                extracted_hist =  qwen_llm([{"role":"user","content":user_input}],"qwen2.5-32b-instruct",extracted_prompt())
                await websocket.send(pack_non_schedule('ground extract'+extracted_hist))
                if "json" in extracted_hist:
                    json_str= extracted_hist.split('json:')[1].strip()
                else :
                    json_str=extracted_hist
                json_data = json.loads(json_str)
                missing_fields = json_data["missing fields"]
                add_msg.append({"role":'assistant',"content":extracted_hist})
                #missing_fields = extracted_hist.split('missing fields:')[1].strip().split('<list_end>')[0].strip()
                extracted_hist =  json_data["extracted information"]
                # still partially completed?

            if len(missing_fields)<1:
                final_extracted=qwen_llm([{"role":"user","content":"correct output format according to sysprompt"}],"qwen2.5-32b-instruct",autofill_prompt())
                if "json" in final_extracted:
                    json_str = final_extracted.split('json:')[1].strip()
                else:
                    json_str=final_extracted
                new_data = json.loads(json_str)
                new_data = new_data['collected events']
                feteched_data =get_add_event(new_data)
                check_conflict = check_time_conflicts(feteched_data,new_data)
                if len (check_conflict)>0:
                    conflict_output="found conflicts, how can I help you solve it? \n "+str(check_conflict)
                    add_msg.append({"role":"assistant","content":f'[conflict checker]: {conflict_output}'})
                    #report conflict
                    await websocket.send(pack_non_schedule(conflict_output))
                    #wait user's input
                    #use the preference to solve the conflict
                    user_input = await websocket.recv()
                    add_msg.append({"role":"user","content":user_input})
                #router_msg.append(("user",user_input)) # this will check what user want to do with the conflict
                #conflict_action = type_agent("chater",router_msg,llm)
                    conflict_action = qwen_llm([add_msg[-1]],"qwen2.5-7b-instruct",chater_prompt()[0])
                    #if cancel, end the dialogue
                    if "delete" in conflict_action:
                        floor_messages.append(add_msg)
                        await websocket.send(pack_non_schedule("The arrangement has been cancelled!"))
                        continue
                        # return "user delete the new events"
                    else:
                        #send it to add planner
                        addplan_msg = add_planner_prompt()
                        addplan_msg.append(("user",user_input))
                        confirm_stat = False # has to be confirmed by user
                        while not confirm_stat:
                            addplan_msg=[{'role':'user','content':'do as the systempromt say'}]
                            response = qwen_llm(addplan_msg,"qwen2.5-32b-instruct",add_planner_prompt()[0])
                            if "json" in response:
                            
                                json_str = response.split('json:')[1].strip()
                            else :
                                json_str=response
                            json_data = json.loads(json_str)
                            addplan_msg.append({"role":"assistant","content":response})
                            try:
                                conflict_res=json_data["Conflict explanation"]   
                                await websocket.send(pack_non_schedule(conflict_res)) 
                                user_input = await websocket.recv()
                                addplan_msg.append({"role":"user","content":user_input})
                                get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                                if get_confirm=="agree":
                                    confirm_stat=True
                            except:
                                solved_plan=json_data["Suggested Schedule"]
                                await websocket.send(pack_non_schedule("OK! conflict solved \n"+str(solved_plan)+"\n Would you confirm?"))
                                user_input = await websocket.recv()
                                addplan_msg.append({"role":"user","content":user_input})

                            #confirm_msg=confirm_agent_prompt()
                            #get_confirm = type_agent("confirm_agent",confirm_msg,llm)
                                get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                                if get_confirm=="agree":
                                    confirm_stat=True
                                # disagree?
                try:
                    final_schedule=json_data["Suggested Schedule"]
                except:
                    final_schedule = new_data
                #send final schedule back to frontend
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                #write_event(final_schedule,user_id)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                #need to delete the event in the new event listed first
                floor_messages.append(add_msg)
                floor_messages.append(addplan_msg)
                continue
                # return "new event has been added"
            else: 
                #information is not enough , call add planner
                #planner need new data, and fetched data 
                
                final_extracted=qwen_llm([{"role":'user',"content":user_input}],"qwen2.5-32b-instruct",autofill_prompt())
                await websocket.send(pack_non_schedule('2 no full extract'+final_extracted))
                
                if "json" in final_extracted:
                    json_str = final_extracted.split('json:')[1].strip()
                else :
                    json_str = final_extracted
     
                new_data = json.loads(json_str) 
                await websocket.send(pack_non_schedule('2 no full format'+str(  new_data) )) 
                new_data = new_data['collected events']
                feteched_data = get_add_event(new_data)
                user_input = None# now user does not have feedback yet
                addplan_msg = add_planner_prompt()
                conflict_res = []
        
                confirm_stat = False # has to be confirmed by user 
                while not confirm_stat:
                    addplan_msg=[{'role':'user','content':'do as the systempromt say'}]
                    response = qwen_llm(addplan_msg,"qwen2.5-32b-instruct",add_planner_prompt()[0])
                    await websocket.send(pack_non_schedule('2 no plan'+str(  response) )) 
                    if "json" in response:
                        json_str = response.split('json:')[1].strip()
                    else :
                        json_str = response
                    json_data = json.loads(json_str)
                    addplan_msg.append({"role":"assistant","content":response})
                    if "conflict explanation:" in response.lower():
                        conflict_res=json_data["Conflict explanation"]
                        if len(conflict_res)>3:
                            addplan_msg.append({"role":"assistant","content":f'[conflict checker]: {conflict_res}'})
                            await websocket.send(pack_non_schedule(conflict_res))
                            user_input = await websocket.recv()
                            addplan_msg.append({"role":"user","content":user_input})

                            get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                            if get_confirm=="agree":
                                confirm_stat=True
                        else:
                            pass
                            # never have conflict
                        solved_plan=json_data["Suggested Schedule"]
                        await websocket.send(pack_non_schedule("OK!\n"+str(solved_plan)+"\n Would you confirm?"))
                        user_input = await websocket.recv()
                        addplan_msg.append({"role":"user","content":user_input})
                    
                        get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                        if get_confirm =="agree":
                            confirm_stat=True
                    else:
                        #conflict has been solved
                        solved_plan= json_data["Suggested Schedule"]
                        await websocket.send(pack_non_schedule("OK! conflict solved \n"+str(solved_plan)+"\n Would you confirm?"))
                        user_input = await websocket.recv()
                        addplan_msg.append({"role":"user","content":user_input})
                    
                        get_confirm = qwen_llm([],"qwen2.5-7b-instruct",confirm_agent_prompt()[0])
                        if get_confirm =="agree":
                            confirm_stat=True

                final_schedule= json_data["Suggested Schedule"]
                #send final schedule back to frontend
                await websocket.send(pack_schedule(json.dumps(final_schedule),'normal'))
                #write_event(final_schedule,user_id)
                await websocket.send(pack_non_schedule("The arrangement has been finished!"))
                try:
                    cancel_events = json.loads(response.lower().split("cancel list:")[1].split("----separate line----")[0].strip())
                    delete_event(cancel_events)
                except ValueError:
                    pass
                
            #add all messages to floor at last
            #the first one is the system prompt, do not add to floor
            floor_messages.append(add_msg)
            floor_messages.append(addplan_msg)
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
                    # print response
                    # await websocket.send(pack_non_schedule(response))
                    # get response in python json format
                    response = json_extract(response.lower().split('[todo_planner]:')[1].strip())
                    # get response in json string format
                    response_str = json.dumps(response)
                    # print response in json string format
                    # await websocket.send(pack_non_schedule(response_str))
                    todo_planner.append(("assistant",response_str))
                    plan_details="event:"+response[0]['description']+"\ncategory:"+response[0]['category']+"\npriority:"+response[0]['priority']+"\nstart date:"+response[0]['start_date']+"\nperiod:"+response[0]['period_description']+"\ntime:"+response[0]['timeslot']+"\nDo you agree with this plan?"
                    # print plan details
                    await websocket.send(pack_non_schedule(plan_details))
                    user_input = await websocket.recv()
                    todo_planner.append(("user",user_input))
                    confirm_msg=confirm_agent_prompt()
                    confirm_msg.append(("user",user_input))
                    get_confirm = llm_invoke(client, "deepseek-chat", confirm_msg, "confirm_agent")
                    if get_confirm.lower().split('[confirm_agent]:')[1].strip()=="agree":
                        confirm_stat=True
                time_slot=response[1]['adjusted_timeslot_details']
                event_list = []
                for slot in time_slot:
                    event = {
                        'event_id': gen_id(),
                        'start_time': slot['date'] + " " + slot['timeslot'].split('-')[0],
                        'end_time': slot['date'] + " " + slot['timeslot'].split('-')[1],
                        'category': response[0]['category'],
                        'description': response[0]['description'],
                        'priority': response[0]['priority'],
                    }
                    event_list.append(event)
                # await websocket.send(pack_non_schedule(json.dumps(event_list)))
                # write event list to database
                await websocket.send(pack_period_schedule(json.dumps(event_list),'period','calendar'))
                write_event(event_list)
                #update the review time of todo
                item['origin_plan']=response[0]['period_description'] +','+ response[0]['timeslot']
                print(type(event_list[-1]['end_time']))
                item['review_time'] = event_list[-1]['end_time'].strftime("%Y-%m-%d") # when the last planned event is complete, review 
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
    return [f"""
role:
you are a sensitive agent that good at judging the user's agreement to the plan.

output:
if the user agree, return "agree"
if the user disagree, return "disagree"
if the user is using a statement, not showing any intention, return "none"

this is user input:{user_input}
"""]

def chater_prompt():
    return [f'''

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
''']

def add_extractor_prompt():
    return [f"""
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

"""]

def add_planner_prompt():
    return [f"""Role: I am a Schedule Planning Specialist that optimizes event scheduling.
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
3. if the key of the JSON does not have value ,leave it empty (e.g.  {{"Conflict explanation":""  }})

(DO NOT USER ANY MARKDOWN FORMAT SYMBOLS )
json:
{{


"Suggested Schedule":
[
    {{
        "event_id": "value",
        "start_time": "value",
        "end_time": "value",
        "category": "value",
        "description": "value",
        "priority": "value"
    }},
    {{}}
],

"Conflict explanation":(only include if conflicts exist)
(Only explain why you give the suggestion when you found conflict, and only explain about the conflict using event names or descriptions,
do not use event id ,do not include others.)
,
"Cancel list":(only include if user want to cancel events)

}}
```

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

"""]


def todo_planner_prompt(cur_date):
    return [{"role":"system","content":f'''
# Role: 
You are an AI schedule agent expert in intelligently inserting recurring events into a user's calendar through holistic time optimization and human-centric reasoning.

# Current Date:
{cur_date}

# Objective:
Find the earliest possible start date and optimal recurring time slot for the user's requested event and schecule for the next 30 days since the start date:
- Avoids conflicts with existing events.
- Follows natural activity sequences (e.g., no sports after sports, buffer before critical meetings).
- Respects time preferences (e.g., no early-morning sports).
- Aligns with event duration norms (e.g., workouts = 45–90 mins).

# Rules:
- Start Date Calculation:
If the user specifies a timeframe (e.g., “starting next week”), calculate the first valid day:
example( if current date is Saturday, then next week should be next monday)
If unspecified, start on the earliest conflict-free day.

- Period Handling:
User Phrase → Period Definition:
"Every week" → Schedule 1 event within each 7-day window (days can vary).
"Every 10 days" → Schedule 1 event every 10-day interval (days can vary).
"Twice a month" → Schedule 2 events, each in separate 15-day windows.
Custom patterns (e.g., "every Mon/Wed/Fri") still apply if explicitly stated.

- Flexible Day Selection:
For each period, dynamically select any day.
If multiple days are valid, prioritize the most suitable day based on user preferences, prefer the same weekday if possible.
Try to balance the numbers of events in each period, for example (do not put everything on monday if other days are so free).

- Time Slot Selection(Apply to Every Occurrence):
-- Prioritization Logic:
Assign desire time slot to high priority events.
First check the most preferred time slot for an event, it does not need to follow the existed event closly.
Consider enough time break between two consecutive quite different events, because extra time is needed to change location or prepare for the next event.
-- Sequence Logic:
Buffer 60+ mins before high-priority meetings.
Separate similar activities (e.g., gym → meeting → yoga, not gym → yoga).
-- Natural Timing:
Creative work: 8:00–11:00 AM.
Exercise: 9:00 AM – 10:00 AM and 16:00PM - 20:00PM.
Meetings: 9:00 AM – 5:00 PM.

- Auto-Assign Attributes and for priority, default to medium unless stated (e.g., “urgent” = high).
- Duration: 
-- Assign based on event type (e.g., workout = 60 mins, meeting = 30 mins).
-- Split a very long duration if is not explicitly a continuous event, the split ones could flexibly select days and time slot trying to balance.

- The time slot could be different for each occurence if needed.

# User preference(you must follow this preference):
Avoid Early Morning Sports: No intense activities (gym, swim) before 9:00 AM.
Do not plan two sports event in the same day.

# User Feedback:
{return_feedback}

# Conflict Resolution
If no slots fit, propose alternatives (e.g., shorten duration, adjust days) with explanations.

**In the output:
- You need to show the final proposed schedule after the dynamic adjustments.
- Date should be presented in YYYY-MM-DD format. (e.g. 2025-04-02).
- Time slot should be presented in 24hour format (e.g. 15:00-16:00).
- Please strictly follow this format:
```json
[
    {{
        "priority": "the priority of the event (1-5)",
        "category": "the category of the event",
        "description": "the description of the event",
        "start_date": "the start date of the event (YYYY-MM-DD)",
        "period_description": "the period description of the event (e.g. everyday)",
        "timeslot": "the time slot of the event (e.g. 15:00-16:00)"
    }},
    {{
        "adjusted_timeslot_details": [
        {{
            "date": "the date of the event (YYYY-MM-DD)",
            "timeslot": "the time slot of the event (e.g. 15:00-16:00)"
        }},
        ...
        ]
    }}
]
```
'''}]

def time_infer_prompt():
    
    return f"""

you should get the start_time from user input.
if the start_time is given in a related form ,you need to infer based on current time.
Do this step by step:
1.decide how many days after current time the event will start
2.attain the date by computing with current time and the days after current time
3.make sure you do not omit a single day

(example: user:i will swim next Friday , if current time is 2025-2-25 Tuesday, next Friday should be 2025-2-28 )

-Note: the current time is  {time}, infer based on this time 
- the format for start_time  is YYYY-MM-DD HH:MM
- you should be aware that Feburary has 28 days in 2025.

output format(strickly follow the format):

reason:
your inferering process

Output:
YYYY-MM-DD HH:MM  (if day and time given)
YYYY-MM-DD  (if day is given and time is not given)
none  (if day and time not given)

"""


def extracted_prompt():
    return f"""
you are a event information collector. you will follow the steps below:

the event fields include :  start_time,end_time,time span,priority,category,description
1.extract  information of the event from user input
- note the start_time is this {start_time}.
- end_time might implicitly give (e.g.   3-4 pm, 3 is start and 4 is end time )
- you could infer this event description if user do not provide description.

2.identify which required fields are missing ,show them in a list
- the required fields :start_time, end_time,priority, category

this is the information that you already know:{extracted_hist} . this is also considered as extracted information


output format(strickly follow the format below)
(DO NOT USER ANY MARKDOWN FORMAT SYMBOLS )
(if the key of the JSON does not have value ,leave it empty (e.g.  {{"Conflict explanation":""  }}))
json:
{{
"reasoning": reason process (1.extract ,2.decide what is missing ),
"extracted information": only show the provided  information and description,
"missing fields":[list of missing fields]
 (- if implicityly end time given, then it is not missing) 
 (- time span is not missing)

}}


"""



def autofill_prompt():
    return f"""


you are a event information collector. you will follow the steps below:

1.infer and fill the missing fields given extracted information , user provided information and missing information
-inference guides:
-you may infer priority (1-5, 1 is most important), category(Work/Personal/Health) and description by your self
- you may infer the end_time given start_time and possible period of this event
- if the start_time and end_time does not have hour, you need to infer it 
2.combine all the information and output the result

the extracted information is this:{extracted_hist}

the event infor includes this :
{{
    "start_time": "YYYY-MM-DD HH:MM", 
    "end_time": "YYYY-MM-DD HH:MM",   
    "category": "Work/Personal/Health",
    "description": "user input",
    "priority": "1-5"
}}


output format(strickly follow the format below)

output:
(DO NOT USER ANY MARKDOWN FORMAT SYMBOLS )
(if the key of the JSON does not have value ,leave it empty (e.g.  {{"Conflict explanation":""  }}))
json:
{{
"resoning":your reasoning process,
"collected events":(list of newly scheduled events) 
[{{}},{{}}](e.g  [{{"start_time":"2024-02-26 14:00","end_time":"2024-02-26 15:00","description":"meeting","priority":"5"}}]   )



}}

```

"""

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
        ping_interval=15,
        ping_timeout=5,
        close_timeout=3600
    ):
        print(f"服务已启动，监听端口 {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
