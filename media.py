from emby import emby
from tmdb import tmdb
from douban import douban
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import zhconv
from log import log
import time
from config import config
from mediasql import mediasql

class media:
    embyclient = None
    tmdbclient = None
    doubanclient = None
    languagelist = None
    threadpool = None
    tasklist = None
    updatepeople = None
    updateoverview = None
    updateseasongroup = None
    taskdonespace = None
    delnotimagepeople = None
    configload = None
    sqlclient = None

    def __init__(self, configinfo : config) -> None:
        """
        :param configinfo 配置
        """
        try:
            self.configload = False
            self.sqlclient = mediasql(cachefailtime=configinfo.systemdata['cachefailtime'])
            self.embyclient = emby(host=configinfo.systemdata['embyhost'], userid=configinfo.systemdata['embyuserid'], key=configinfo.systemdata['embykey'])
            self.tmdbclient = tmdb(key=configinfo.systemdata['tmdbkey'])
            self.doubanclient = douban(key=configinfo.systemdata['doubankey'], cookie=configinfo.systemdata['doubancookie'])
            self.languagelist = ['zh-CN', 'zh-SG', 'zh-TW', 'zh-HK']
            self.threadpool = ThreadPoolExecutor(max_workers=configinfo.systemdata['threadnum'])
            self.tasklist = []
            self.updatepeople = configinfo.systemdata['updatepeople']
            self.updateoverview = configinfo.systemdata['updateoverview']
            self.taskdonespace = configinfo.systemdata['taskdonespace']
            self.delnotimagepeople = configinfo.systemdata['delnotimagepeople']
            self.updateseasongroup = configinfo.systemdata['updateseasongroup']
            self.configload = True
        except Exception as reuslt:
            log.info('配置异常错误, {}'.format(reuslt))

    def start_scan_media(self):
        """
        开始扫描媒体
        :return True or False
        """
        if not self.configload:
            log.info('配置未正常加载')
            return False
        #获取媒体库根文件夹
        ret, itmes = self.embyclient.get_items()
        if not ret:
            log.info('获取Emby媒体总列表失败, {}'.format(self.embyclient.err))
            return False
        self.tasklist = []
        ret = self.__check_media_info__(itemlist=itmes)
        log.info('总媒体数量[{}]'.format(len(self.tasklist)))
        for task in as_completed(self.tasklist):
            ret, name = task.result()
            if ret:
                log.info('媒体[{}]处理完成'.format(name))
            else:
                log.info('媒体[{}]处理失败'.format(name))
        return ret

    def __check_media_info__(self, itemlist):
        """
        检查媒体信息
        :param itemlist 项目列表
        :return True or False
        """
        try:
            for item in itemlist['Items']:
                if 'Folder' in item['Type'] and ('CollectionType' not in item or 'boxsets' not in item['CollectionType']):
                    ret, items = self.embyclient.get_items(parentid=item['Id'])
                    if not ret:
                        log.info('获取Emby媒体[{}]ID[{}]列表失败, {}'.format(item['Name'], item['Id'], self.embyclient.err))
                        continue
                    self.__check_media_info__(itemlist=items)
                else:
                    if 'Series' in item['Type'] or 'Movie' in item['Type']:
                        task = self.threadpool.submit(self.__to_deal_with_item__, item)
                        self.tasklist.append(task)


            return True     
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False
        
    def __to_deal_with_item__(self, item):
        """
        处理媒体
        :param item
        :return True or False
        """
        try:
            updatename = False
            updatepeople = False
            updateoverview = False
            ret, iteminfo = self.embyclient.get_item_info(itemid=item['Id'])
            if not ret:
                log.info('获取Emby媒体[{}]ID[{}]信息失败, {}'.format(item['Name'], item['Id'], self.embyclient.err))
                return False, item['Name']
            if 'LockedFields' not in iteminfo:
                iteminfo['LockedFields'] = []
            tmdbid = None
            imdbid = None
            if 'Tmdb' in iteminfo['ProviderIds']:
                tmdbid = iteminfo['ProviderIds']['Tmdb']
            elif 'tmdb' in iteminfo['ProviderIds']:
                tmdbid = iteminfo['ProviderIds']['tmdb']

            if 'Imdb' in iteminfo['ProviderIds']:
                imdbid = iteminfo['ProviderIds']['Imdb']
            elif 'imdb' in iteminfo['ProviderIds']:
                imdbid = iteminfo['ProviderIds']['imdb']
            
            doubanmediainfo = None
            doubancelebritiesinfo = None  

            if not self.__is_chinese__(string=item['Name']):                

                if not tmdbid and not imdbid:
                    log.info('Emby媒体[{}]ID[{}]Tmdb|Imdb不存在'.format(item['Name'], item['Id']))
                    return False, item['Name']
                name = None
                if tmdbid:
                    if 'Series' in item['Type']:
                        ret, name = self.__get_tmdb_media_name__(mediatype=1, datatype=1, id=tmdbid)
                    else:
                        ret, name = self.__get_tmdb_media_name__(mediatype=2, datatype=1, id=tmdbid)
                if imdbid and not name:
                    if 'Series' in item['Type']:
                        ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=1, name=item['Name'], id=imdbid)
                    else:
                        ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=2, name=item['Name'], id=imdbid)
                    if ret:
                        if self.__is_chinese__(string=doubanmediainfo['title'], mode=2):
                            name = doubanmediainfo['title']
                
                if name:
                    originalname = iteminfo['Name']
                    iteminfo['Name'] = name
                    if 'Name' not in iteminfo['LockedFields']:
                        iteminfo['LockedFields'].append('Name')
                    updatename = True

      
            if self.updatepeople and 'People' in iteminfo:
                for people in iteminfo['People']:
                    ret, peopleinfo = self.embyclient.get_item_info(itemid=people['Id'])
                    if not ret:
                        log.info('获取Emby人物信息失败, {}'.format(self.embyclient.err))
                        continue
                    
                    peopleimdbid = None
                    peopletmdbid = None
                    peoplename = None
                    if 'Tmdb' in peopleinfo['ProviderIds']:
                        peopletmdbid = peopleinfo['ProviderIds']['Tmdb']
                    elif 'tmdb' in peopleinfo['ProviderIds']:
                        peopletmdbid = peopleinfo['ProviderIds']['tmdb']

                    if 'Imdb' in peopleinfo['ProviderIds']:
                        peopleimdbid = peopleinfo['ProviderIds']['Imdb']
                    elif 'imdb' in peopleinfo['ProviderIds']:
                        peopleimdbid = peopleinfo['ProviderIds']['imdb']

                    if not self.__is_chinese__(string=people['Name'], mode=1):
                        if 'LockedFields' not in peopleinfo:
                            peopleinfo['LockedFields'] = []

                        if not peopletmdbid and not peopleimdbid:
                            log.info('Emby人物[{}]ID[{}]Tmdb|Imdb不存在'.format(peopleinfo['Name'], peopleinfo['Id']))
                            continue


                        if peopleimdbid and imdbid:
                            if not doubanmediainfo:
                                if 'Series' in item['Type']:
                                    ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=1, name=item['Name'], id=imdbid)
                                else:
                                    ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=2, name=item['Name'], id=imdbid)

                            if doubanmediainfo and not doubancelebritiesinfo:
                                if 'Series' in item['Type']:
                                    ret, doubancelebritiesinfo = self.__get_douban_media_celebrities_info__(mediatype=1, id=doubanmediainfo['id'])
                                else:
                                    ret, doubancelebritiesinfo = self.__get_douban_media_celebrities_info__(mediatype=2, id=doubanmediainfo['id'])
                            
                            if doubancelebritiesinfo:
                                ret, celebrities = self.__get_people_info__(celebritiesinfo=doubancelebritiesinfo, people=people, imdbid=peopleimdbid)
                                if ret and self.__is_chinese__(string=celebrities['name']):
                                    peoplename = re.sub(pattern='\s+', repl='', string=celebrities['name'])
                        if not peoplename:
                            if self.__is_chinese__(string=peopleinfo['Name'], mode=2):
                                peoplename = re.sub(pattern='\s+', repl='', string=peopleinfo['Name'])
                                peoplename = zhconv.convert(peopleinfo['Name'], 'zh-cn')
                            elif peopletmdbid:
                                ret, peoplename = self.__get_tmdb_person_name(personid=peopletmdbid)

                        if peoplename:
                            originalpeoplename = people['Name']
                            peopleinfo['Name'] = peoplename
                            if 'Name' not in peopleinfo['LockedFields']:
                                peopleinfo['LockedFields'].append('Name')
                            people['Name'] = peoplename
                            ret = self.embyclient.set_item_info(itemid=peopleinfo['Id'], iteminfo=peopleinfo)
                            if ret:
                                log.info('原始人物名称[{}]更新为[{}]'.format(originalpeoplename, peoplename))
                                updatepeople = True
                    elif 'Role' not in people or not self.__is_chinese__(string=people['Role'], mode=2):
                        if imdbid:
                            if not doubanmediainfo:
                                if 'Series' in item['Type']:
                                    ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=1, name=item['Name'], id=imdbid)
                                else:
                                    ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=2, name=item['Name'], id=imdbid)
                            
                            if doubanmediainfo and not doubancelebritiesinfo:
                                if 'Series' in item['Type']:
                                    ret, doubancelebritiesinfo = self.__get_douban_media_celebrities_info__(mediatype=1, id=doubanmediainfo['id'])
                                else:
                                    ret, doubancelebritiesinfo = self.__get_douban_media_celebrities_info__(mediatype=2, id=doubanmediainfo['id'])

                            if peopleimdbid and doubanmediainfo and doubancelebritiesinfo:
                                ret, celebrities = self.__get_people_info__(celebritiesinfo=doubancelebritiesinfo, people=people, imdbid=peopleimdbid)
                                if ret:
                                    if self.__is_chinese__(string=re.sub(pattern='饰\s+', repl='', string=celebrities['character'])):
                                        people['Role'] = re.sub(pattern='饰\s+', repl='', string=celebrities['character'])
                                        updatepeople = True
                                    doubanname = re.sub(pattern='\s+', repl='', string=celebrities['name'])
                                    if people['Name'] != doubanname and self.__is_chinese__(string=doubanname):
                                        originalpeoplename = people['Name']
                                        peopleinfo['Name'] = doubanname
                                        people['Name'] = doubanname
                                        ret = self.embyclient.set_item_info(itemid=peopleinfo['Id'], iteminfo=peopleinfo)
                                        if ret:
                                            log.info('原始人物名称[{}]更新为[{}]'.format(originalpeoplename, people['Name']))
                                            updatepeople = True
                                
                    time.sleep(0.1)
                
                directorpeoples = []
                actorpeoples = []
                peoples = []
                for people in iteminfo['People']:
                    if self.delnotimagepeople:
                        if 'PrimaryImageTag' not in people:
                            updatepeople = True
                            continue
                    if people['Type'] == 'Director':
                        if people['Name'] not in directorpeoples:
                            directorpeoples.append(people['Name'])
                            peoples.append(people)
                        else:
                            updatepeople = True
                    elif people['Type'] == 'Actor':
                        if people['Name'] not in actorpeoples:
                            actorpeoples.append(people['Name'])
                            peoples.append(people)
                        else:
                            updatepeople = True
                iteminfo['People'] = peoples

            if self.updateoverview:
                if 'Overview' not in iteminfo or not self.__is_chinese__(string=iteminfo['Overview']):
                    if not tmdbid and not imdbid:
                        log.info('Emby媒体[{}]ID[{}]Tmdb|Imdb不存在'.format(item['Name'], item['Id']))
                        return False, item['Name']
                    ret = False
                    if tmdbid:
                        if 'Series' in item['Type']:
                            ret, overview = self.__get_tmdb_media_name__(mediatype=1, datatype=2, id=tmdbid)
                        else:
                            ret, overview = self.__get_tmdb_media_name__(mediatype=2, datatype=2, id=tmdbid)
                    if ret:
                        iteminfo['Overview'] = overview
                        if 'Overview' not in iteminfo['LockedFields']:
                            iteminfo['LockedFields'].append('Overview')
                        updateoverview = True
                    elif imdbid:
                        if not doubanmediainfo:
                            if 'Series' in item['Type']:
                                ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=1, name=item['Name'], id=imdbid)
                            else:
                                ret, doubanmediainfo = self.__get_douban_media_info__(mediatype=2, name=item['Name'], id=imdbid)
                        if doubanmediainfo:
                            if doubanmediainfo['intro']:
                                iteminfo['Overview'] = doubanmediainfo['intro']
                                if 'Overview' not in iteminfo['LockedFields']:
                                    iteminfo['LockedFields'].append('Overview')
                                updateoverview = True

                
                if 'Series' in item['Type']:
                    ret, seasons = self.embyclient.get_items(parentid=item['Id'])
                    if not ret:
                        log.info('获取Emby媒体[{}]ID[{}]信息失败, {}'.format(item['Name'], item['Id'], self.embyclient.err))
                    else:
                        tvinfo = None
                        seasongroupinfo = None
                        seasonserr = False
                        seasonnum = 0
                        if tmdbid and self.updateseasongroup:
                            ret, tvinfo = self.__get_tmdb_media_info__(mediatype=1, id=tmdbid)
                            for season in seasons['Items']:
                                if season['IndexNumber'] <= 0:
                                    continue
                                seasonnum += 1
                            if ret and seasonnum > tvinfo['number_of_seasons']:
                                seasonserr = True
                        for season in seasons['Items']:
                            ret, episodes = self.embyclient.get_items(parentid=season['Id'])
                            if not ret:
                                log.info('获取Emby媒体[{}]ID[{}]信息失败, {}'.format(season['Name'], season['Id'], self.embyclient.err))
                                continue
                            for episode in episodes['Items']:
                                ret, episodeinfo = self.embyclient.get_item_info(itemid=episode['Id'])
                                if not ret:
                                    log.info('获取Emby媒体[{}]ID[{}]信息失败, {}'.format(episode['Name'], episode['Id'], self.embyclient.err))
                                else:
                                    imageurl = None
                                    name = None
                                    overview = None
                                    if not seasonserr:
                                        if 'Overview' not in episodeinfo or not self.__is_chinese__(string=episodeinfo['Overview']):
                                            ret, name, overview = self.__get_tmdb_tv_season_info__(tvid=tmdbid, seasonid=season['IndexNumber'], episodeid=episode['IndexNumber'])
                                            if not ret:
                                                continue
                                    else:
                                        if not seasongroupinfo:
                                            if not tvinfo:
                                                continue
                                            if 'episode_groups' not in tvinfo or 'results' not in tvinfo['episode_groups']:
                                                log.info('媒体[{}]ID[{}]季数量异常, TMDB查找剧集组数据失败', item['Name'], item['Id'])
                                                continue
                                            ret, seasongroupinfo = self.__get_tmdb_tv_season_group_info__(seasongroup=tvinfo['episode_groups']['results'], seasonnum=seasonnum)
                                            if not ret:
                                                continue
                                        if int(season['IndexNumber']) <= 0 or int(season['IndexNumber']) > len(seasongroupinfo['groups']):
                                            continue
                                        seasoninfo = seasongroupinfo['groups'][int(season['IndexNumber']) - 1]
                                        if int(episode['IndexNumber']) <= 0 or int(episode['IndexNumber']) > len(seasoninfo['episodes']):
                                            continue
                                        tmdbepisodeinfo = seasoninfo['episodes'][int(episode['IndexNumber']) - 1]
                                        if tmdbepisodeinfo['name'] != episodeinfo['Name']:
                                            name = tmdbepisodeinfo['name']
                                        if 'Overview' not in episodeinfo or tmdbepisodeinfo['overview'] != episodeinfo['Overview']:
                                            overview = tmdbepisodeinfo['overview']
                                        if 'still_path' in tmdbepisodeinfo and len(tmdbepisodeinfo['still_path']):
                                            imageurl = 'https://www.themoviedb.org/t/p/original{}'.format(tmdbepisodeinfo['still_path'])
                                        
                                    if not name or not overview:
                                        continue
                                    if 'LockedFields' not in episodeinfo:
                                        episodeinfo['LockedFields'] = []
                                    episodeinfo['Name'] = name
                                    episodeinfo['Overview'] = overview
                                    if 'Name' not in episodeinfo['LockedFields']:
                                        episodeinfo['LockedFields'].append('Name')
                                    if 'Overview' not in episodeinfo['LockedFields']:
                                        episodeinfo['LockedFields'].append('Overview')
                                    ret = self.embyclient.set_item_info(itemid=episodeinfo['Id'], iteminfo=episodeinfo)
                                    if ret:
                                        log.info('原始媒体名称[{}] 第[{}]季 第[{}]集更新概述'.format(iteminfo['Name'], season['IndexNumber'], episode['IndexNumber']))
                                    if imageurl:
                                        ret = self.embyclient.set_item_image(itemid=episodeinfo['Id'], imageurl=imageurl)
                                        if ret:
                                            log.info('原始媒体名称[{}] 第[{}]季 第[{}]集更新图片'.format(iteminfo['Name'], season['IndexNumber'], episode['IndexNumber']))

            if not updatename and not updatepeople and not updateoverview:
                return True, item['Name']
            ret = self.embyclient.set_item_info(itemid=iteminfo['Id'], iteminfo=iteminfo)
            if ret:
                if updatename:
                    log.info('原始媒体名称[{}]更新为[{}]'.format(originalname, iteminfo['Name']))
                if updatepeople:
                    log.info('原始媒体名称[{}]更新人物'.format(iteminfo['Name']))
                if updateoverview:
                    log.info('原始媒体名称[{}]更新概述'.format(iteminfo['Name']))
            time.sleep(self.taskdonespace)
            return True, item['Name']
                    
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, item['Name']

    def __get_people_info__(self, celebritiesinfo, people, imdbid):
        """
        获取人物信息
        :param celebritiesinfo 演员信息
        :param 人物信息
        :param imdbid
        """
        try:
            if people['Type'] == 'Director':
                for celebrities in celebritiesinfo['directors']:
                    if 'info' not in celebrities:
                        continue
                    haspeople = False
                    for imdb in celebrities['info']['extra']['info']:
                        if imdb[0] != 'IMDb编号':
                            continue
                        if imdb[1] == imdbid:
                            haspeople = True
                            break
                                        
                    if haspeople:
                        return True, celebrities

                for celebrities in celebritiesinfo['directors']:
                    if people['Name'] == celebrities['name'] or people['Name'] == celebrities['latin_name']:
                        return True, celebrities
                                
            if people['Type'] == 'Actor':
                for celebrities in celebritiesinfo['actors']:
                    if 'info' not in celebrities:
                        continue
                    haspeople = False
                    for imdb in celebrities['info']['extra']['info']:
                        if imdb[0] != 'IMDb编号':
                            continue
                        if imdb[1] == imdbid:
                            haspeople = True
                            break
                                        
                    if haspeople:
                        return True, celebrities

                for celebrities in celebritiesinfo['actors']:
                    if people['Name'] == celebrities['name'] or people['Name'] == celebrities['latin_name']:
                        return True, celebrities
            
            return False, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None   

    def __get_douban_media_celebrities_info__(self, mediatype : int, id : str):
        """
        获取豆瓣媒体演员信息
        :param mediatype 媒体类型 1TV 2电影
        :id id 媒体ID
        :return True or False, celebritiesinfo
        """
        try:
            ret, celebritiesinfo = self.sqlclient.get_douban_celebrities_info(mediatype=mediatype, id=id)
            if not ret:
                if mediatype == 1:
                    ret, celebritiesinfo = self.doubanclient.get_tv_celebrities_info(tvid=id)
                else:
                    ret, celebritiesinfo = self.doubanclient.get_movie_celebrities_info(movieid=id)
                if not ret:
                    log.info('获取豆瓣媒体ID[{}]演员信息失败, {}'.format(id, self.doubanclient.err))
                    return False, None
                ret = self.sqlclient.write_douban_celebrities_info(mediatype=mediatype, id=id, iteminfo=celebritiesinfo)
                if not ret:
                    log.info('保存豆瓣媒体ID[{}]演员信息失败, {}'.format(id, self.doubanclient.err))
            for celebrities in  celebritiesinfo['directors']:
                ret, info = self.sqlclient.get_douban_people_info(id=celebrities['id'])
                if not ret:
                    ret, info = self.doubanclient.get_celebrity_info(celebrityid=celebrities['id'])
                    if not ret:
                        log.info('获取豆瓣媒体ID[{}]演员信息失败, {}'.format(id, self.doubanclient.err))
                        continue
                    ret = self.sqlclient.write_douban_people_info(id=celebrities['id'], iteminfo=info)
                    if not ret:
                        log.info('获取豆瓣媒体ID[{}]演员信息失败, {}'.format(id, self.doubanclient.err))
                celebrities['info'] = info
            for celebrities in  celebritiesinfo['actors']:
                ret, info = self.sqlclient.get_douban_people_info(id=celebrities['id'])
                if not ret:
                    ret, info = self.doubanclient.get_celebrity_info(celebrityid=celebrities['id'])
                    if not ret:
                        log.info('获取豆瓣媒体ID[{}]演员[{}]ID[{}]信息失败, {}'.format(id, celebrities['name'], celebrities['id'], self.doubanclient.err))
                        continue
                    ret = self.sqlclient.write_douban_people_info(id=celebrities['id'], iteminfo=info)
                    if not ret:
                        log.info('保存豆瓣媒体ID[{}]演员[{}]ID[{}]信息失败, {}'.format(id, celebrities['name'], celebrities['id'], self.doubanclient.err))
                celebrities['info'] = info
            return True, celebritiesinfo
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None   

    def __get_douban_media_info__(self, mediatype : int, name : str, id : str):
        """
        获取豆瓣媒体信息
        :param mediatype 媒体类型 1TV 2电影
        :name name 媒体名称
        :id imdb
        :return True or False, mediainfo
        """
        try:
            ret, items = self.sqlclient.search_douban_media(mediatype=mediatype, title=name)
            if not ret:
                ret, items = self.doubanclient.search_media_pc(name)
                if not ret:
                    ret, items = self.doubanclient.search_media(name)
                if not ret:
                    ret, items = self.doubanclient.search_media_weixin(name)
                if not ret:
                    log.info('豆瓣搜索媒体[{}]失败, {}'.format(name, str(self.doubanclient.err)))
                    return False, None

            for item in items['items']:
                if mediatype == 1:
                    if 'target_type' in item and item['target_type'] != 'tv':
                        continue
                elif mediatype == 2:
                    if 'target_type' in item and item['target_type'] != 'movie':
                        continue
                ret, mediainfo = self.sqlclient.get_douban_media_info(mediatype=mediatype, id=item['target_id'])
                if not ret:
                    if mediatype == 2:
                        ret, mediainfo = self.doubanclient.get_movie_info(movieid=item['target_id'])
                    else:
                        ret, mediainfo = self.doubanclient.get_tv_info(tvid=item['target_id'])
                    if not ret:
                        log.info('获取豆瓣媒体[{}]ID[{}]信息失败, {}'.format(item['title'], item['target_id'], self.doubanclient.err))
                        return False, None
                    ret = self.sqlclient.write_douban_media_info(mediatype=mediatype, id=item['target_id'], iteminfo=mediainfo)
                    if not ret:
                        log.info('保存豆瓣媒体[{}]ID[{}]信息失败, {}'.format(item['title'], item['target_id'], self.doubanclient.err))
                if 'IMDb' not in mediainfo['info']:
                    continue
                if mediainfo['info']['IMDb'] == id:
                    ret = self.sqlclient.write_douban_media(mediatype=mediatype, id=item['target_id'], iteminfo=item)
                    if not ret:
                        log.info('保存豆瓣媒体[{}]ID[{}]信息失败, {}'.format(item['title'], item['target_id'], self.doubanclient.err))
                    return True, mediainfo
            return False, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None    

    def __get_tmdb_media_info__(self, mediatype : int, id : str, language : str = 'zh-CN'):
        """
        获取tmdb媒体信息
        :param mediatype 媒体类型 1TV 2电影
        :param id tmdbid
        :return True or False, name
        """
        try:
            iteminfo = None
            if mediatype == 1:
                ret, iteminfo = self.sqlclient.get_tmdb_media_info(mediatype=mediatype, id=id, language=language)
                if not ret:
                    ret, iteminfo = self.tmdbclient.get_tv_info(tvid=id, language=language)
                    if not ret:
                        log.info('获取TMDB媒体ID[{}]信息失败, {}'.format(id, self.tmdbclient.err))
                        return False, None
                    ret = self.sqlclient.write_tmdb_media_info(mediatype=mediatype, id=id, language=language, iteminfo=iteminfo)
                    if not ret:
                        log.info('保存TMDB媒体ID[{}]信息失败, {}'.format(id, self.tmdbclient.err))
                return True, iteminfo
            else:
                ret, iteminfo = self.sqlclient.get_tmdb_media_info(mediatype=mediatype, id=id, language=language)
                if not ret:
                    ret, iteminfo = self.tmdbclient.get_movie_info(movieid=id, language=language)
                    if not ret:
                        log.info('获取TMDB媒体ID[{}]信息失败, {}'.format(id, self.tmdbclient.err))
                        return False, None
                    ret = self.sqlclient.write_tmdb_media_info(mediatype=mediatype, id=id, language=language, iteminfo=iteminfo)
                    if not ret:
                        log.info('保存TMDB媒体ID[{}]信息失败, {}'.format(id, self.tmdbclient.err))
                return True, iteminfo
            return False, iteminfo
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None

    def __get_tmdb_media_name__(self, mediatype : int, datatype : int, id : str):
        """
        获取tmdb媒体中文名称
        :param mediatype 媒体类型 1TV 2电影
        :param datatype 数据类型 1名字 2概述
        :param id tmdbid
        :return True or False, name
        """
        try:
            for language in self.languagelist:
                if mediatype == 1:
                    ret, tvinfo = self.__get_tmdb_media_info__(mediatype=mediatype, id=id, language=language)
                    if not ret:
                        continue
                    if datatype == 1:
                        if self.__is_chinese__(string=tvinfo['name']):
                            if self.__is_chinese__(string=tvinfo['name'], mode=3):
                                return True, zhconv.convert(tvinfo['name'], 'zh-cn')
                            return True, tvinfo['name']
                        else:
                            ret, name = self.__alternative_name__(alternativetitles=tvinfo)
                            if not ret:
                                continue
                            return True, name
                    else:
                        if self.__is_chinese__(string=tvinfo['overview']):
                            if self.__is_chinese__(string=tvinfo['overview'], mode=3):
                                return True, zhconv.convert(tvinfo['overview'], 'zh-cn')
                            return True, tvinfo['overview']
                else:
                    ret, movieinfo = self.__get_tmdb_media_info__(mediatype=mediatype, id=id, language=language)
                    if not ret:
                        continue
                    if datatype == 1:
                        if self.__is_chinese__(string=movieinfo['title']):
                            if self.__is_chinese__(string=movieinfo['title'], mode=3):
                                return True, zhconv.convert(movieinfo['title'], 'zh-cn')
                            return True, movieinfo['title']
                        else:
                            ret, name = self.__alternative_name__(alternativetitles=movieinfo)
                            if not ret:
                                continue
                            return True, name
                    else:
                        if self.__is_chinese__(string=movieinfo['overview']):
                            if self.__is_chinese__(string=movieinfo['overview'], mode=3):
                                return True, zhconv.convert(movieinfo['overview'], 'zh-cn')
                            return True, movieinfo['overview']
                    
            return False, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None

    def __get_tmdb_tv_season_group_info__(self, seasongroup, seasonnum : int):
        """
        获取TMDB电视剧季组信息
        :param seasongroup 组信息
        :param seasonnum 季数量
        :return True or False, iteminfo
        """
        try:
            for season in seasongroup:
                if int(season['group_count']) != seasonnum:
                    continue
                for language in self.languagelist:
                    ret, iteminfo = self.tmdbclient.get_tv_season_group(groupid=season['id'], language=language)
                    if not ret:
                        log.info('获取TMDB剧集组ID[{}]信息失败, {}', season['id'], self.tmdbclient.err)
                        continue
                    return True, iteminfo
            return False, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None

    def __get_tmdb_tv_season_info__(self, tvid : str, seasonid : str, episodeid : int):
        """
        获取tmdb季中文
        :param tvid tmdbid
        :param seasonid 季ID
        :param episodeid 集ID
        :return True or False, name, overview
        """
        try:
            for language in self.languagelist:
                ret, seasoninfo = self.sqlclient.get_tmdb_season_info(id=tvid, language=language)
                if not ret:
                    ret, seasoninfo = self.tmdbclient.get_tv_season_info(tvid=tvid, seasonid=seasonid, language=language)
                    if not ret:
                        log.info('获取TMDB媒体ID[{}]季ID[{}]信息失败, {}'.format(tvid, seasonid, self.tmdbclient.err))
                        continue
                    ret = self.sqlclient.write_tmdb_season_info(id=tvid, language=language, iteminfo=seasoninfo)
                    if not ret:
                        log.info('保存TMDB媒体ID[{}]季ID[{}]信息失败, {}'.format(tvid, seasonid, self.tmdbclient.err))
                for episodes in seasoninfo['episodes']:
                    if episodes['episode_number'] > episodeid:
                        break
                    if episodes['episode_number'] != episodeid:
                        continue
                    if self.__is_chinese__(string=episodes['overview']):
                        if self.__is_chinese__(string=episodes['name'], mode=3):
                            name = zhconv.convert(episodes['name'], 'zh-cn')
                        else:
                            name = episodes['name']
                        if self.__is_chinese__(string=episodes['overview'], mode=3):
                            overview = zhconv.convert(episodes['overview'], 'zh-cn')
                        else:
                            overview = episodes['overview']
                        return True, name, overview

            return False, None, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None, None

    def __get_tmdb_person_name(self, personid):
        """
        获取tmdb人物中文
        :param personid 人物ID
        :return True or False, name
        """
        try:
            for language in self.languagelist:
                ret, personinfo = self.sqlclient.get_tmdb_people_info(id=personid, language=language)
                if not ret:
                    ret, personinfo = self.tmdbclient.get_person_info(personid=personid, language=language)
                    if not ret:
                        log.info('获取TMDB人物ID[{}]信息失败, {}'.format(personid, self.tmdbclient.err))
                        continue
                    ret = self.sqlclient.write_tmdb_people_info(id=personid, language=language, iteminfo=personinfo)
                    if not ret:
                        log.info('保存TMDB人物ID[{}]信息失败, {}'.format(personid, self.tmdbclient.err))
                for name in personinfo['also_known_as']:
                    if not self.__is_chinese__(string=name, mode=2):
                        continue
                    if self.__is_chinese__(string=name, mode=3):
                        name = zhconv.convert(name, 'zh-cn')
                    return True, re.sub(pattern='\s+', repl='', string=name)
                break
            return False, None
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None

    def __alternative_name__(self, alternativetitles):
        """
        返回别名中文名称
        :return True or False, name
        """
        try:
            if 'alternative_titles' not in alternativetitles or 'titles' not in alternativetitles['alternative_titles']:
                return False, None
            for title in alternativetitles['alternative_titles']['titles']:
                if 'iso_3166_1' not in title:
                    continue
                if title['iso_3166_1'] != 'CN':
                    continue
                if not self.__is_chinese__(string=title['title']):
                    continue
                if self.__is_chinese__(string=title['title'], mode=3):
                    return True, zhconv.convert(title['title'], 'zh-cn')
                return True, title['title']
        except Exception as result:
            log.info("异常错误：{}".format(result))
            return False, None


    def __is_chinese__(self, string : str, mode : int = 1):
        """
        判断是否包含中文
        :param string 需要判断的字符
        :param mode 模式 1匹配简体和繁体 2只匹配简体 3只匹配繁体
        :return True or False
        """
        for ch in string:
            if mode == 1:
                if '\u4e00' <= ch <= '\u9FFF':
                    return True
            elif mode == 2:
                if '\u4e00' <= ch <= '\u9FFF':
                    if zhconv.convert(ch, 'zh-cn') == ch:
                        return True
            elif mode == 3:
                if '\u4e00' <= ch <= '\u9FFF':
                    if zhconv.convert(ch, 'zh-cn') != ch:
                        return True
        if re.match(pattern='^[0-9]+$', string=string):
            return True
        return False