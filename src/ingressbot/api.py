import copy
import json
import logging
import lxml.html
import requests
from StringIO import StringIO

MAX_AUTH_RETRIES = 1

HANDSHAKE_PARAMS = {
  "nemesisSoftwareVersion" : "2013-06-28T23:28:27Z 760a7a8ffc90 opt", 
  "deviceSoftwareVersion" : "4.1.1"
}
URLS = {
  "CLIENT_LOGIN" : "https://www.google.com/accounts/ClientLogin",
  "SERVICE_LOGIN" : "https://accounts.google.com/ServiceLoginAuth",
  "APPENGINE" : "https://appengine.google.com",
  "GAME_API" : "https://betaspike.appspot.com",
  "INGRESS" : "http://www.ingress.com"
}
PATHS = {
  "LOGIN" : "/_ah/login",
  "CONFLOGIN" : "/_ah/conflogin",
  "API" : {
    "HANDSHAKE" : "/handshake",
    "DROP_ITEM" : "/rpc/gameplay/dropItem",
    "RECYCLE" : "/rpc/gameplay/recycleItem",
    "SAY" : "/rpc/player/say",
    "INVENTORY" : "/rpc/playerUndecorated/getInventory",
    "PLEXTS" : "/rpc/playerUndecorated/getPaginatedPlexts"
  },
  "INTEL" : {
    "BASE" : "/intel",
    "PLEXTS" : "/rpc/dashboard.getPaginatedPlextsV2"
  }
}
HEADERS = {
  "HANDSHAKE" : {      
    "Accept-Charset" : "utf-8",
    "Cache-Control" : "max-age=0"
  },
  "API" : {
    "Content-Type" : "application/json;charset=UTF-8", 
    "User-Agent" : "Nemesis (gzip)"
  },
  "INTEL" : {
    "Referer" : r"http://www.ingress.com/intel",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.95 Safari/537.11"
  }
}

class Api(object):

  def __init__(self, email, password):
    self.userEmail = email
    self.userPassword = password
    self.headers = copy.deepcopy(HEADERS)
    self.authApi(self.userEmail, self.userPassword)
    self.authIntel(self.userEmail, self.userPassword)
    self.logger = logging.getLogger("ingressbot")
      
  def authApi(self, email, password):
    authParams = {"Email":   email, "Passwd":  password, "service": "ah", "source":  "IngressBot", "accountType": "HOSTED_OR_GOOGLE"}
    request =  requests.post(URLS["CLIENT_LOGIN"], allow_redirects=False, data=authParams)
    status = int(request.status_code)
    response = dict(x.split("=") for x in request.content.split("\n") if x)
    if(status == 200):
      try:
        authToken = response["Auth"]
      except:
        raise RuntimeError("Authentication failed: Bad Response")
    elif(status == 403):
      error = response["Error"]
      if(error == "BadAuthentication"):
        raise RuntimeError("Authentication failed: Username or password wrong")
      elif(error == "NotVerified"):
        raise RuntimeError("Authentication failed: Account email address has not been verified")
      elif(error == "TermsNotAgreed"):
        raise RuntimeError("Authentication failed: User has not agreed to Googles terms of service")
      elif(error == "CaptchaRequired"):
        raise RuntimeError("Authentication failed: CAPTCHA required")
      elif(error == "AccountDeleted"):
        raise RuntimeError("Authentication failed: User account has been deleted")
      elif(error == "AccountDisabled"):
        raise RuntimeError("Authentication failed: User account has been disabled")
      elif(error == "ServiceDisabled"):
        raise RuntimeError("Authentication failed: Service disabled")
      elif(error == "ServiceUnavailable"):
        raise RuntimeError("Authentication failed: Service unavailable")
      else:
        raise RuntimeError("Authentication failed: Unknown reason")
    else:
      raise RuntimeError("Authentication failed: Bad Response")
    
    request = requests.get(URLS["GAME_API"] + PATHS["LOGIN"], allow_redirects=False, params={"auth" : authToken})
    self.cookiesApi = request.cookies

    urlParams = {"json" : json.dumps(HANDSHAKE_PARAMS)}
    request = requests.get(URLS["GAME_API"] + PATHS["API"]["HANDSHAKE"], verify=False, allow_redirects=False, params=urlParams, headers=self.headers["HANDSHAKE"], cookies=self.cookiesApi)
    try:
      handshakeResult = json.loads(request.content.replace("while(1);", ""))["result"]
    except:
      raise RuntimeError("Authentication with Ingress severs failed for unknown reason.")
    if(handshakeResult["versionMatch"] != "CURRENT"):
      raise RuntimeError("Software version not up-to-date")
    if("xsrfToken" not in handshakeResult):
      raise RuntimeError("Authentication with Ingress severs failed for unknown reason")
    self.headers["API"]["X-XsrfToken"] = handshakeResult["xsrfToken"]
    self.nickname = handshakeResult["nickname"]
    self.playerGUID = handshakeResult["playerEntity"][0]
    
  def authIntel(self, email, password):
    params = {"service" : "ah" , "passive" : "true", "continue" : URLS["APPENGINE"] + PATHS["CONFLOGIN"] + "?continue=http://www.ingress.com/intel"}
    request = requests.get(URLS["SERVICE_LOGIN"], params=params, verify=False)
    tree = lxml.html.parse(StringIO(request.content))
    root = tree.getroot()
    for form in root.xpath('//form[@id="gaia_loginform"]'):
        for field in form.getchildren():
            if 'name' in field.keys():
              name = field.get('name')
              if name == "dsh":
                params["dsh"] = field.get('value')
              elif name == "GALX":
                params["GALX"] = field.get('value')
    params["Email"] = email
    params["Passwd"] = password
    
    request = requests.post(URLS["SERVICE_LOGIN"], cookies=request.cookies, data=params, verify=False)
    hasSID = False
    hasCSRF = False
    for cookie in request.cookies:
      if cookie.name == "ACSID":
        hasSID = True
      if cookie.name == "csrftoken":
        hasCSRF = True
        self.headers["INTEL"]["X-CSRFToken"] = cookie.value
        
    if hasSID and hasCSRF:
      self.cookiesIntel = request.cookies
      return
    
    tree = lxml.html.parse(StringIO(request.content))
    root = tree.getroot()
    for field in root.xpath('//input'):
      if 'name' in field.keys():
        if field.get('name') == "state":
          params["state"] = field.get('value')
    params["submit_true"] = "Allow"
    
    request = requests.post(URLS["APPENGINE"] + PATHS["CONFLOGIN"], cookies=request.cookies, data=params, verify=False)
    hasSID = False
    hasCSRF = False
    for cookie in request.cookies:
      if cookie.name == "ACSID":
        hasSID = True
      if cookie.name == "csrftoken":
        hasCSRF = True
        self.headers["INTEL"]["X-CSRFToken"] = cookie.value
    if not (hasSID and hasCSRF):
      raise RuntimeError("Authentication failed: Unknown reason")
    self.cookiesIntel = request.cookies
  
  def _apiWrap(self, func, authRetry=0, **kwargs):
    response = func(**kwargs)
    if response.status_code == 200:
      try:
        return json.loads(response.content.replace("while(1);", ""))
      except:
        self.logger.critical("headers: " + str(response.headers))
        self.logger.critical("content: " + str(response.content))
        raise
    elif response.status_code == 401:
      if(authRetry >= MAX_AUTH_RETRIES):
        self.logger.critical("headers: " + str(response.headers))
        self.logger.critical("content: " + str(response.content))
        raise RuntimeError("Re-Authentication failed")
      else:
        self.logger.critical("RE-AUTHENTICATION")
        self.authApi(self.userEmail, self.userPassword)
        return self._apiWrap(func, authRetry=authRetry+1, **kwargs)
    elif response.status_code == 500:
      return dict()

  def _getInventory(self, lastQueryTimestamp):
    return requests.post(
      URLS["GAME_API"] + PATHS["API"]["INVENTORY"],
      cookies=self.cookiesApi, allow_redirects=False, headers=self.headers["API"], 
      data=json.dumps({"params" : {"lastQueryTimestamp": lastQueryTimestamp}})
    )

  def getInventory(self, lastQueryTimestamp):
    return self._apiWrap(self._getInventory, lastQueryTimestamp=lastQueryTimestamp)
    
  def getMessages(self, bounds, minTimestamp, maxTimestamp, maxItems, factionOnly):
    payload = {
      "factionOnly" : factionOnly,
      "desiredNumItems" : maxItems,
      "minLatE6": bounds["minLatE6"],
      "minLngE6" : bounds["minLngE6"],
      "maxLatE6" : bounds["maxLatE6"],
      "maxLngE6" : bounds["maxLngE6"],
      "minTimestampMs" : minTimestamp,
      "maxTimestampMs" : maxTimestamp,
      "method" : "dashboard.getPaginatedPlextsV2"
    }
    response = requests.post(URLS["INGRESS"] + PATHS["INTEL"]["PLEXTS"], allow_redirects=False, cookies=self.cookiesIntel, headers=self.headers["INTEL"], data = json.dumps(payload))
    try:
      return json.loads(response.content)
    except:
      self.logger.critical("status: " + str(response.status_code))
      self.logger.critical("headers: " + str(response.headers))
      self.logger.critical("content: " + str(response.content))
      raise
