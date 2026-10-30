import { useState } from 'react';
import { router } from 'expo-router';
import { Button, Card, Field, Screen, colors, styles } from '../components/ui';
import { useAuth } from '../providers/AuthProvider';
import { Pressable, Text, View } from 'react-native';
import { configureApiBaseUrl, getApiBaseUrl } from '../lib/api';

const portalOptions = [
  { id: 'institution', label: 'Institution' },
  { id: 'official', label: 'AICTE Official' },
  { id: 'admin', label: 'Administrator' },
];

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[portal,setPortal]=useState('institution');
  const [apiUrl,setApiUrl]=useState(getApiBaseUrl()),[showApiUrl,setShowApiUrl]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');

  async function submit() {
    setError('');setBusy(true);
    try {
      await configureApiBaseUrl(apiUrl);
      const result=await signIn(email.trim(),password,portal);
      router.replace(result.mfaRequired?'/mfa':'/(portal)');
    } catch(e) { setError(e.message||'Sign in could not be completed.'); }
    finally { setBusy(false); }
  }

  return <Screen title="AICTE FDR Portal" subtitle="Sign in to securely manage and review Fixed Deposit Receipts.">
    <Card><Text style={{fontSize:17,fontWeight:'800',color:colors.ink}}>Choose your portal</Text>
      <View style={{flexDirection:'row',gap:8,flexWrap:'wrap'}}>{portalOptions.map(item=><Pressable key={item.id} onPress={()=>setPortal(item.id)} style={{paddingHorizontal:12,paddingVertical:9,borderRadius:20,borderWidth:1,borderColor:portal===item.id?colors.blue:colors.line,backgroundColor:portal===item.id?'#EAF1FB':colors.white}}><Text style={{fontWeight:'700',fontSize:12,color:portal===item.id?colors.blue:colors.muted}}>{item.label}</Text></Pressable>)}</View>
      <Field label="Email address" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none"/>
      <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none"/>
      {error?<Text accessibilityRole="alert" style={{color:'#B42318',fontSize:13}}>{error}</Text>:null}
      <Button title={busy?'Signing in…':'Sign in'} onPress={submit} disabled={busy||!email.trim()||!password}/>
      <Pressable onPress={()=>setShowApiUrl(value=>!value)}><Text style={{color:colors.muted,fontSize:12,textAlign:'center'}}>Server connection settings</Text></Pressable>
      {showApiUrl&&<><Field label="Portal API URL" value={apiUrl} onChangeText={setApiUrl} autoCapitalize="none" placeholder="https://portal.example.org/api/v1"/><Text style={styles.small}>For Android Emulator local development, use http://10.0.2.2:8000/api/v1. For a physical phone, use a reachable HTTPS backend URL.</Text></>}
    </Card>
    <Text style={[styles.muted,{textAlign:'center'}]}>Access is controlled by your assigned portal role. Your session tokens are stored in the device’s secure storage.</Text>
  </Screen>;
}
