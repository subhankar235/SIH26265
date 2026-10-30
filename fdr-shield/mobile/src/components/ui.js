import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';

export const colors = { navy: '#142843', blue: '#2868C7', pale: '#F3F6FA', ink: '#172638', muted: '#66758A', line: '#D8E0EA', white: '#FFFFFF', green: '#19734D', amber: '#9A6700', red: '#B42318' };

export function Screen({ title, subtitle, children, onRefresh, refreshing = false }) {
  return <View style={styles.root}><StatusBar barStyle="dark-content" backgroundColor={colors.pale}/>
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.blue}/> : undefined}>
      {!!title&&<View style={styles.heading}><Text style={styles.title}>{title}</Text>{!!subtitle&&<Text style={styles.subtitle}>{subtitle}</Text>}</View>}
      {children}
    </ScrollView>
  </View>;
}

export function Card({ children, style }) { return <View style={[styles.card, style]}>{children}</View>; }

export function Button({ title, onPress, secondary = false, disabled = false, compact = false, danger = false }) {
  return <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled}
    style={({ pressed }) => [styles.button, compact&&styles.buttonCompact,
      secondary&&styles.buttonSecondary, danger&&styles.buttonDanger,
      (pressed||disabled)&&styles.buttonDim]}>
    <Text style={[styles.buttonText, secondary&&styles.buttonSecondaryText, danger&&styles.buttonDangerText]}>{title}</Text>
  </Pressable>;
}

export function Field({ label, value, onChangeText, placeholder, secureTextEntry, keyboardType, multiline, editable = true, autoCapitalize }) {
  return <View style={styles.field}><Text style={styles.label}>{label}</Text><TextInput value={value} onChangeText={onChangeText}
    placeholder={placeholder||label} placeholderTextColor="#8A97A7" secureTextEntry={secureTextEntry}
    keyboardType={keyboardType} multiline={multiline} editable={editable} autoCapitalize={autoCapitalize||'sentences'}
    style={[styles.input, multiline&&styles.multiline, !editable&&styles.readOnly]}/></View>;
}

export function Loading({ label = 'Loading…' }) { return <Card style={styles.center}><ActivityIndicator size="small" color={colors.blue}/><Text style={styles.muted}>{label}</Text></Card>; }
export function ErrorMessage({ message, onRetry }) { return <Card style={styles.errorCard}><Text style={styles.errorTitle}>Couldn’t load this information</Text><Text style={styles.errorText}>{message||'Check your connection and try again.'}</Text>{onRetry&&<Button title="Try again" onPress={onRetry} secondary compact/>}</Card>; }
export function Empty({ title, message, action }) { return <Card style={styles.empty}><Text style={styles.sectionTitle}>{title}</Text><Text style={styles.muted}>{message}</Text>{action}</Card>; }
export function Badge({ children, tone = 'neutral' }) { return <View style={[styles.badge, tone==='green'&&styles.badgeGreen,tone==='amber'&&styles.badgeAmber,tone==='red'&&styles.badgeRed]}><Text style={[styles.badgeText,tone==='green'&&styles.badgeGreenText,tone==='amber'&&styles.badgeAmberText,tone==='red'&&styles.badgeRedText]}>{children}</Text></View>; }

export function useApiResource(loader, intervalMs = 0) {
  const [data,setData]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[refreshing,setRefreshing]=useState(false);
  const refresh=useCallback(async (pull=false)=>{
    if(pull)setRefreshing(true);
    try{const result=await loader();setData(result);setError('');return result;}
    catch(e){setError(e.message||'Request failed.');throw e;}
    finally{if(pull)setRefreshing(false);setLoading(false);}
  },[loader]);
  useEffect(()=>{
    let active=true;
    const settle=result=>{if(!active)return;setData(result);setError('');setLoading(false);setRefreshing(false);};
    const fail=e=>{if(!active)return;setError(e.message||'Request failed.');setLoading(false);setRefreshing(false);};
    loader().then(settle).catch(fail);
    const timer=intervalMs?setInterval(()=>{
      setRefreshing(true);
      loader().then(settle).catch(e=>{if(!active)return;setError(e.message||'Request failed.');setRefreshing(false);});
    },intervalMs):null;
    return()=>{active=false;if(timer)clearInterval(timer);};
  },[loader,intervalMs]);
  return {data,error,loading,refreshing,refresh};
}

export const styles=StyleSheet.create({
  root:{flex:1,backgroundColor:colors.pale},page:{padding:18,paddingBottom:36,gap:14},heading:{marginBottom:4},title:{fontSize:26,fontWeight:'800',color:colors.ink},subtitle:{fontSize:14,lineHeight:20,color:colors.muted,marginTop:5},card:{backgroundColor:colors.white,borderColor:colors.line,borderWidth:1,borderRadius:14,padding:15,gap:9},sectionTitle:{fontSize:16,fontWeight:'700',color:colors.ink},muted:{color:colors.muted,fontSize:13,lineHeight:19},label:{fontSize:13,fontWeight:'600',color:colors.ink,marginBottom:5},field:{marginBottom:10},input:{borderWidth:1,borderColor:colors.line,borderRadius:10,paddingHorizontal:12,paddingVertical:11,fontSize:15,color:colors.ink,backgroundColor:colors.white},multiline:{minHeight:90,textAlignVertical:'top'},readOnly:{backgroundColor:'#F3F5F8',color:colors.muted},button:{backgroundColor:colors.navy,borderRadius:10,paddingVertical:13,paddingHorizontal:15,alignItems:'center',justifyContent:'center',minHeight:46},buttonCompact:{minHeight:36,paddingVertical:8,paddingHorizontal:11,alignSelf:'flex-start'},buttonSecondary:{backgroundColor:'#EAF1FB'},buttonDanger:{backgroundColor:'#FDECEC'},buttonText:{color:colors.white,fontWeight:'700',fontSize:14},buttonSecondaryText:{color:colors.navy},buttonDangerText:{color:colors.red},buttonDim:{opacity:.58},center:{alignItems:'center',paddingVertical:24},errorCard:{borderColor:'#F1C5C2',backgroundColor:'#FFF8F7'},errorTitle:{fontWeight:'700',color:colors.red},errorText:{color:'#6E3B39',fontSize:13,lineHeight:19},empty:{alignItems:'flex-start',paddingVertical:20},badge:{backgroundColor:'#EFF2F6',borderRadius:20,paddingHorizontal:9,paddingVertical:5,alignSelf:'flex-start'},badgeText:{fontSize:11,fontWeight:'700',color:'#526173'},badgeGreen:{backgroundColor:'#E7F5ED'},badgeGreenText:{color:colors.green},badgeAmber:{backgroundColor:'#FFF2D6'},badgeAmberText:{color:colors.amber},badgeRed:{backgroundColor:'#FDECEC'},badgeRedText:{color:colors.red},row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:10},divider:{height:1,backgroundColor:colors.line},kpi:{flex:1,minWidth:'43%',backgroundColor:colors.white,borderColor:colors.line,borderWidth:1,borderRadius:12,padding:13},kpiValue:{fontSize:21,fontWeight:'800',color:colors.ink},kpiLabel:{fontSize:11,color:colors.muted,marginTop:4},grid:{flexDirection:'row',flexWrap:'wrap',gap:9},tile:{width:'48%',minHeight:92,justifyContent:'space-between'},tileTitle:{fontSize:14,fontWeight:'700',color:colors.ink},link:{fontSize:13,fontWeight:'700',color:colors.blue},notice:{backgroundColor:'#EBF3FF',borderColor:'#C9DBF8',borderWidth:1,borderRadius:12,padding:13},noticeText:{fontSize:13,lineHeight:19,color:'#254A7A'},listRow:{gap:6},small:{fontSize:12,color:colors.muted},modalBackdrop:{flex:1,justifyContent:'flex-end',backgroundColor:'rgba(10,22,38,.42)'},modal:{backgroundColor:colors.white,padding:20,borderTopLeftRadius:18,borderTopRightRadius:18,gap:10},modalTitle:{fontSize:18,fontWeight:'800',color:colors.ink},toolbar:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',paddingHorizontal:18,paddingVertical:11,backgroundColor:colors.white,borderBottomWidth:1,borderBottomColor:colors.line},toolbarTitle:{fontSize:14,fontWeight:'700',color:colors.ink},smallButton:{paddingVertical:7,paddingHorizontal:9},
});
