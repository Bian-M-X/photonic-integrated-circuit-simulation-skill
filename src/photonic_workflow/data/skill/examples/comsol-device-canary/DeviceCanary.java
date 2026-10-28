import com.comsol.model.*;
import com.comsol.model.util.*;
import java.util.*;

/** Original bounded 2D scalar-index canary. No vendor model or private checkpoint. */
public final class DeviceCanary {
  static final String STAGE="__STAGE__", SHAPE="__SHAPE__";
  static void require(boolean b,String why){if(!b)throw new IllegalStateException(why);}
  static void marker(String s){System.out.println("CANARY "+s);}
  static Set<Integer> ids(int[] a){Set<Integer>s=new TreeSet<>();for(int x:a)s.add(x);return s;}
  static void box(Model m,String tag,double x0,double x1,double y0,double y1){
    m.component("c").selection().create(tag,"Box");
    m.component("c").selection(tag).set("entitydim",1);
    m.component("c").selection(tag).set("condition","inside");
    m.component("c").selection(tag).set("xmin",x0);m.component("c").selection(tag).set("xmax",x1);
    m.component("c").selection(tag).set("ymin",y0);m.component("c").selection(tag).set("ymax",y1);
  }
  static void rect(GeomSequence g,String t,double y,double h){
    g.create(t,"Rectangle");g.feature(t).set("pos",new double[]{0,y});g.feature(t).set("size",new double[]{14,h});
  }
  static void material(Model m,String t,String sel,String n){
    m.component("c").material().create(t,"Common");m.component("c").material(t).selection().named(sel);
    m.component("c").material(t).propertyGroup().create("RefractiveIndex","Refractive index");
    m.component("c").material(t).propertyGroup("RefractiveIndex").set("n",new String[]{n});
    m.component("c").material(t).propertyGroup("RefractiveIndex").set("ki",new String[]{"0"});
    m.component("c").material(t).propertyGroup("def").set("relpermeability",new String[]{"1","0","0","0","1","0","0","0","1"});
    m.component("c").material(t).propertyGroup("def").set("electricconductivity",new String[]{"0","0","0","0","0","0","0","0","0"});
  }
  static void auditDomains(Model m){
    Set<Integer> core=ids(m.component("c").selection("g_core_dom").entities(2));
    Set<Integer> bg=ids(m.component("c").selection("bg").entities(2));
    Set<Integer> all=ids(m.component("c").selection("allDomains").entities(2));
    require(!core.isEmpty()&&!bg.isEmpty(),"Empty semantic domains");
    Set<Integer> both=new TreeSet<>(core);both.retainAll(bg);require(both.isEmpty(),"Material overlap");
    Set<Integer> union=new TreeSet<>(core);union.addAll(bg);require(union.equals(all),"Material coverage");
    for(String tag:new String[]{"coremat","clad"}){
      String sel=tag.equals("coremat")?"g_core_dom":"bg";
      int[] entities=m.component("c").material(tag).selection().entities(2);
      require(ids(entities).equals(ids(m.component("c").selection(sel).entities(2))),"Material assignment mismatch");
      // 6.4 finalized-entity API; measure() addresses pre-finalization geometry objects.
      m.component("c").geom("g").measureFinal().selection().geom("g",2);
      m.component("c").geom("g").measureFinal().selection().set(entities);
      double area=m.component("c").geom("g").measureFinal().getVolume();
      double[] bounds=m.component("c").geom("g").measureFinal().getBoundingBox();
      marker("MATERIAL "+tag+" selection="+sel+" entities="+Arrays.toString(entities)+" area="+area+" bbox="+Arrays.toString(bounds)+" n="+Arrays.toString(m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("n"))+" ki="+Arrays.toString(m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("ki")));
      double expected=tag.equals("coremat")?(SHAPE.equals("straight")?4.2:4.28):(SHAPE.equals("straight")?65.8:65.72);
      // Finalized geometry uses float-represented vertices: observed .15 -> .15000000596046448 um.
      // This 1e-6 um^2 representation tolerance is separate from all physical acceptance limits.
      require(Math.abs(area-expected)<1e-6,"Semantic area mismatch "+area+" expected "+expected);
      double expectedN=tag.equals("coremat")?2.6:1.45;
      for(String n:m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("n"))require(Math.abs(Double.parseDouble(n)-expectedN)<1e-12,"Native n mismatch");
      for(String ki:m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("ki"))require(Double.parseDouble(ki)==0,"Native ki mismatch");
      double half=tag.equals("coremat")?(SHAPE.equals("straight")?.15:.17):2.5;
      double[] expectedBox={0,14,-half,half};require(bounds.length==4,"Native bbox dimension");for(int i=0;i<4;i++)require(Math.abs(bounds[i]-expectedBox[i])<1e-8,"Native bbox mismatch");
    }
    marker("MATERIAL_AUDIT_PASS");
  }
  static void auditBoundary(Model m){
    Set<Integer> exterior=ids(m.component("c").selection("exterior").entities(1));
    Set<Integer> seen=new TreeSet<>();
    for(String s:new String[]{"p1","p2","open"}){
      int[] es=m.component("c").selection(s).entities(1);require(es.length>0,"Empty "+s);
      for(int e:es)require(seen.add(e),"Boundary overlap");marker("BOUNDARY "+s+" "+Arrays.toString(es));
    }
    require(seen.equals(exterior),"Incomplete exterior partition");marker("EXTERIOR_PARTITION_PASS "+exterior);
  }
  static Model build(){
    Model m=ModelUtil.create("Canary");m.modelPath(".");m.label("Original device canary "+SHAPE);
    m.param().set("lambda0","1550[nm]");m.param().set("f0","c_const/lambda0");
    m.component().create("c",true);m.component("c").geom().create("g",2);GeomSequence g=m.component("c").geom("g");g.lengthUnit("um");
    rect(g,"lower",-2.5,1.3);rect(g,"center",-1.2,2.4);rect(g,"upper",1.2,1.3);
    g.create("core","Polygon");g.feature("core").set("source","table");
    double h=SHAPE.equals("straight")?.15:.17;
    g.feature("core").set("table",new double[][]{{0,-.15},{5,-.15},{7,-h},{9,-.15},{14,-.15},{14,.15},{9,.15},{7,h},{5,.15},{0,.15}});
    g.feature("core").set("type","solid");g.feature("core").set("selresult","on");g.run();
    m.component("c").selection().create("allDomains","Explicit");m.component("c").selection("allDomains").geom("g",2);m.component("c").selection("allDomains").all();
    m.component("c").selection().create("bg","Difference");m.component("c").selection("bg").set("entitydim",2);m.component("c").selection("bg").set("add",new String[]{"allDomains"});m.component("c").selection("bg").set("subtract",new String[]{"g_core_dom"});
    material(m,"coremat","g_core_dom","2.6");material(m,"clad","bg","1.45");auditDomains(m);
    box(m,"p1",-.001,.001,-1.201,1.201);box(m,"p2",13.999,14.001,-1.201,1.201);
    m.component("c").selection().create("exterior","Explicit");m.component("c").selection("exterior").geom("g",2,1,new String[]{"exterior"});m.component("c").selection("exterior").all();
    m.component("c").selection().create("open","Difference");m.component("c").selection("open").set("entitydim",1);m.component("c").selection("open").set("add",new String[]{"exterior"});m.component("c").selection("open").set("subtract",new String[]{"p1","p2"});auditBoundary(m);
    m.component("c").physics().create("ewfd","ElectromagneticWavesFrequencyDomain","g");m.component("c").physics("ewfd").prop("components").set("components","outofplane");m.component("c").physics("ewfd").feature("wee1").set("DisplacementFieldModel","RefractiveIndex");
    for(int k=1;k<=2;k++){
      String t="port"+k;m.component("c").physics("ewfd").create(t,"Port",1);m.component("c").physics("ewfd").feature(t).selection().named("p"+k);
      m.component("c").physics("ewfd").feature(t).set("PortType","Numeric");m.component("c").physics("ewfd").feature(t).set("PortName",""+k);m.component("c").physics("ewfd").feature(t).set("Pin","1[W/m]");m.component("c").physics("ewfd").feature(t).set("Thetap","0");m.component("c").physics("ewfd").feature(t).set("PortExcitation","on");
      m.component("c").cpl().create("intp"+k,"Integration");m.component("c").cpl("intp"+k).selection().geom("g",1);m.component("c").cpl("intp"+k).selection().named("p"+k);
      marker("PORT "+k+" orientation="+(k==1?"outward_minus_x":"outward_plus_x")+" reference_x_um="+(k==1?0:14)+" phase="+m.component("c").physics("ewfd").feature(t).getString("Thetap")+" Pin="+m.component("c").physics("ewfd").feature(t).getString("Pin"));
      require("Numeric".equals(m.component("c").physics("ewfd").feature(t).getString("PortType")),"Native port type");
      require((""+k).equals(m.component("c").physics("ewfd").feature(t).getString("PortName")),"Native port order");
      require("0".equals(m.component("c").physics("ewfd").feature(t).getString("Thetap")),"Native mode phase");
      require("1[W/m]".equals(m.component("c").physics("ewfd").feature(t).getString("Pin")),"Native normalization");
      require(ids(m.component("c").physics("ewfd").feature(t).selection().entities(1)).equals(ids(m.component("c").selection("p"+k).entities(1))),"Native port selection");
    }
    m.component("c").physics("ewfd").create("sctr","Scattering",1);m.component("c").physics("ewfd").feature("sctr").selection().named("open");
    m.component("c").cpl().create("intopen","Integration");m.component("c").cpl("intopen").selection().geom("g",1);m.component("c").cpl("intopen").selection().named("open");
    m.component("c").cpl().create("intabs","Integration");m.component("c").cpl("intabs").selection().geom("g",2);m.component("c").cpl("intabs").selection().named("allDomains");
    m.component("c").mesh().create("mesh");m.component("c").mesh("mesh").feature("size").set("custom",true);m.component("c").mesh("mesh").feature("size").set("hmax","0.18[um]");m.component("c").mesh("mesh").feature("size").set("hmin","0.01[um]");
    m.component("c").mesh("mesh").create("coreSize","Size");m.component("c").mesh("mesh").feature("coreSize").selection().geom("g",2);m.component("c").mesh("mesh").feature("coreSize").selection().named("g_core_dom");m.component("c").mesh("mesh").feature("coreSize").set("custom",true);m.component("c").mesh("mesh").feature("coreSize").set("hmax","0.035[um]");m.component("c").mesh("mesh").create("tri","FreeTri");
    m.study().create("std");for(int k=1;k<=2;k++)bma(m,"std","bma"+k,k,1);
    m.study("std").create("drive","FrequencyDomainSourceSweep");m.study("std").feature("drive").set("plist","f0");
    marker("STUDY "+Arrays.toString(m.study("std").feature().tags())+" driven_type="+m.study("std").feature("drive").getType());
    require(Arrays.equals(m.study("std").feature().tags(),new String[]{"bma1","bma2","drive"}),"Native study order");
    require("FrequencyDomainSourceSweep".equals(m.study("std").feature("drive").getType()),"Native study type");
    require("RefractiveIndex".equals(m.component("c").physics("ewfd").feature("wee1").getString("DisplacementFieldModel")),"Native material field model");
    for(int k=1;k<=2;k++)marker("BMA_BINDING "+k+"="+m.study("std").feature("bma"+k).getString("PortName")+" shift="+m.study("std").feature("bma"+k).getString("shift")+" neigs="+m.study("std").feature("bma"+k).getInt("neigs"));
    for(int k=1;k<=2;k++)require((""+k).equals(m.study("std").feature("bma"+k).getString("PortName"))&&m.study("std").feature("bma"+k).getInt("neigs")==1,"Native selected mode binding");
    marker("CONFIGURATION_PASS no_mesh_no_mode_no_driven");return m;
  }
  static void bma(Model m,String study,String t,int p,int n){
    m.study(study).create(t,"BoundaryModeAnalysis");m.study(study).feature(t).set("PortName",""+p);m.study(study).feature(t).set("modeFreq","f0");m.study(study).feature(t).set("shift","2.2");m.study(study).feature(t).set("neigs",n);m.study(study).feature(t).set("neigsactive",true);
  }
  static double[] flat(double[][] a){int n=0;for(double[] r:a)n+=r.length;double[]v=new double[n];int i=0;for(double[]r:a)for(double x:r)v[i++]=x;return v;}
  static double[][] series(Model m,String d,String e){
    m.result().numerical().create("probe","Global");try{m.result().numerical("probe").set("data",d);m.result().numerical("probe").set("expr",new String[]{e});double[][][]re=m.result().numerical("probe").getData(),im=m.result().numerical("probe").getImagData();double[]a=flat(re[0]);return new double[][]{a,im==null?new double[a.length]:flat(im[0])};}finally{m.result().numerical().remove("probe");}
  }
  static void direct(SolverFeature f){
    marker("SOLVER_FEATURE "+f.tag()+" "+f.getType());
    if("Stationary".equals(f.getType())){
      if(!Arrays.asList(f.feature().tags()).contains("canaryDirect"))f.create("canaryDirect","Direct");
      f.feature("canaryDirect").set("linsolver","pardiso");
      for(String child:f.feature().tags())if("FullyCoupled".equals(f.feature(child).getType()))f.feature(child).set("linsolver","canaryDirect");
    }
    for(String t:f.feature().tags())if(!t.equals("canaryDirect"))direct(f.feature(t));
  }
  static String dataset(Model m,String sol){for(String d:m.result().dataset().tags())if("Solution".equals(m.result().dataset(d).getType())&&sol.equals(m.result().dataset(d).getString("solution")))return d;throw new IllegalStateException("No actual dataset "+sol);}
  static void field(Model m,String d,String tag,String selection,String[] expressions){
    m.result().numerical().create(tag,"Eval");m.result().numerical(tag).set("data",d);
    if(selection!=null){m.result().numerical(tag).selection().geom("g",1);m.result().numerical(tag).selection().named(selection);}
    m.result().numerical(tag).set("expr",expressions);m.result().numerical(tag).set("refine",1);m.result().numerical(tag).set("smooth","none");
    double[][][]v=m.result().numerical(tag).getData();require(v.length==expressions.length,"Field expression axis");
    require(v[0].length==2,"Field actual source axis");
    for(int s=0;s<2;s++)for(int i=0;i<v[0][s].length;i++){
      StringBuilder b=new StringBuilder("CANARY "+tag+" ");for(int e=0;e<v.length;e++){if(e>0)b.append(',');b.append(v[e][s][i]);}System.out.println(b);
    }
    marker("EXPORT_COMPLETE "+tag+" "+Arrays.toString(expressions));m.result().numerical().remove(tag);
  }
  static void solve(Model m)throws Exception{
    throw new IllegalStateException("Driven path requires accepted persisted selected-mode checkpoint; use resumeDriven");
  }
  static void modes(Model m)throws Exception{
    m.component("c").mesh("mesh").run();marker("MESH_COMPLETE");
    for(int k=1;k<=2;k++){
      String t="census"+k;m.study().create(t);bma(m,t,"mode",k,6);m.study(t).run();
      String sol=null;for(String s:m.sol().tags())if(t.equals(m.sol(s).study()))sol=s;
      require(sol!=null,"Census solution not identified");double[][]neff=series(m,dataset(m,sol),"ewfd.neff_"+k);require(neff[0].length==6,"Missing census pairs");
      int bound=0;for(int i=0;i<neff[0].length;i++){marker("CENSUS "+k+","+i+","+neff[0][i]+","+neff[1][i]);if(neff[0][i]>1.45&&neff[0][i]<2.6&&Math.abs(neff[1][i])<1e-6)bound++;}require(bound==1,"Expected exactly one sampled bound branch, got "+bound);
    }
    String driven=null;
    for(String s:m.sol().tags())if("std".equals(m.sol(s).study())&&m.sol(s).feature().tags().length>0){require(driven==null,"Ambiguous driven sequence");driven=s;}
    require(driven!=null,"No main sequence");
    String[] tags=m.sol(driven).feature().tags();String lastStore=null,driveStart=null;
    for(String tag:tags){
      if("StoreSolution".equals(m.sol(driven).feature(tag).getType()))lastStore=tag;
      if("StudyStep".equals(m.sol(driven).feature(tag).getType())&&"drive".equals(m.sol(driven).feature(tag).getString("studystep")))driveStart=tag;
    }
    require(lastStore!=null&&driveStart!=null,"Cannot safely split automatic sequence");
    marker("RUN_TO_SELECTED "+driven+"/"+lastStore+" future_driven_start="+driveStart);
    m.sol(driven).run(lastStore);marker("SELECTED_RUN_TO_COMPLETED");m.save("selected_modes.mph");
    int port=0;
    for(String tag:tags)if("StoreSolution".equals(m.sol(driven).feature(tag).getType())){
      port++;require(port<=2,"Extra selected-mode store");
      String stored=m.sol(driven).feature(tag).getString("sol");String ds=dataset(m,stored);
      marker("SELECTED_DATASET port="+port+" dataset="+ds+" solution="+stored+" solnum=1");
      String suf=""+port;
      double[][] nr=series(m,ds,"ewfd.neff_"+suf),wl=series(m,ds,"c_const/freq/1[nm]"),power=series(m,ds,"intp"+suf+"(-0.5*real(ewfd.tEmodez_"+suf+"*conj(ewfd.tHmodey_"+suf+"))*nx)/(1[W/m])");
      require(nr[0].length==1&&wl[0].length==1&&power[0].length==1,"Selected scalar identity/count");
      marker("SELECTED_SCALAR "+port+","+nr[0][0]+","+nr[1][0]+","+wl[0][0]+","+power[0][0]);
      m.result().numerical().create("selectedField","Eval");m.result().numerical("selectedField").set("data",ds);
      m.result().numerical("selectedField").selection().geom("g",1);m.result().numerical("selectedField").selection().named("p"+port);
      m.result().numerical("selectedField").set("expr",new String[]{"y/1[um]","real(ewfd.tEmodez_"+suf+")","imag(ewfd.tEmodez_"+suf+")","real(ewfd.tHmodey_"+suf+")","imag(ewfd.tHmodey_"+suf+")"});
      m.result().numerical("selectedField").set("refine",2);m.result().numerical("selectedField").set("smooth","none");
      double[][][]v=m.result().numerical("selectedField").getData();require(v.length==5&&v[0].length==1,"Selected field dimensions");
      for(int i=0;i<v[0][0].length;i++)marker("SELECTED_FIELD "+port+","+v[0][0][i]+","+v[1][0][i]+","+v[2][0][i]+","+v[3][0][i]+","+v[4][0][i]);
      m.result().numerical().remove("selectedField");
    }
    require(port==2,"Missing selected stores");marker("MODES_COMPLETED");
  }
  static void resumeDriven(Model m)throws Exception{
    auditDomains(m);auditBoundary(m);
    require(Arrays.equals(m.study("std").feature().tags(),new String[]{"bma1","bma2","drive"}),"Persisted study identity mismatch");
    for(int k=1;k<=2;k++){
      require((""+k).equals(m.study("std").feature("bma"+k).getString("PortName")),"Persisted BMA binding");
      require("Numeric".equals(m.component("c").physics("ewfd").feature("port"+k).getString("PortType")),"Persisted port type");
      require(ids(m.component("c").physics("ewfd").feature("port"+k).selection().entities(1)).equals(ids(m.component("c").selection("p"+k).entities(1))),"Persisted port selection");
    }
    marker("CONFIGURATION_PASS persisted_checkpoint_readback");
    String driven=null,driveStart=null;
    for(String s:m.sol().tags())if("std".equals(m.sol(s).study())&&m.sol(s).feature().tags().length>0)driven=s;
    require(driven!=null,"No persisted driven sequence");
    for(String tag:m.sol(driven).feature().tags())if("StudyStep".equals(m.sol(driven).feature(tag).getType())&&"drive".equals(m.sol(driven).feature(tag).getString("studystep")))driveStart=tag;
    require(driveStart!=null,"No persisted drive start");
    marker("RESUME_FROM_FROZEN "+driven+"/"+driveStart);
    m.sol(driven).runFrom(driveStart);m.save("driven_checkpoint.mph");marker("DRIVEN_CHECKPOINT_SAVED");
    String d=dataset(m,driven);marker("ACTUAL_DATASET "+d+" solution="+driven+" pnames="+Arrays.toString(m.sol(driven).getPNames())+" pvalues="+Arrays.toString(m.sol(driven).getPVals()));
    double[][]sources=series(m,d,"PortName"),waves=series(m,d,"c_const/freq/1[nm]");require(sources[0].length==2&&waves[0].length==2,"Source/wavelength count");
    for(int j=0;j<2;j++){
      require(Math.abs(sources[0][j]-(j+1))<1e-9&&Math.abs(waves[0][j]-1550)<1e-7,"Actual source/lambda mismatch");marker("SOURCE "+(j+1)+","+sources[0][j]+","+waves[0][j]);
      for(int i=1;i<=2;i++){double[][]s=series(m,d,"ewfd.S"+i+(j+1));require(s[0].length==2&&s[1].length==2,"S axis mismatch");require(Double.isFinite(s[0][j])&&Double.isFinite(s[1][j]),"Nonfinite physical S");marker("S "+(j+1)+","+i+","+(j+1)+","+s[0][j]+","+s[1][j]);}
      String[]ex={"intopen(ewfd.Poavx*nx+ewfd.Poavy*ny)/(1[W/m])","intabs(ewfd.Qh)/(1[W/m])","intp1(ewfd.Poavx*nx+ewfd.Poavy*ny)/(1[W/m])","intp2(ewfd.Poavx*nx+ewfd.Poavy*ny)/(1[W/m])","real(ewfd.neff_1)","real(ewfd.neff_2)"};
      StringBuilder p=new StringBuilder("POWER "+(j+1));for(String e:ex){double[][]v=series(m,d,e);require(v[0].length==2&&Double.isFinite(v[0][j]),"Power axis/nonfinite "+e);p.append(',').append(v[0][j]);}marker(p.toString());
    }
    field(m,d,"FIELD",null,new String[]{"PortName","c_const/freq/1[nm]","x/1[um]","y/1[um]","ewfd.normE^2","log10(max(ewfd.normE^2,1e-30))","real(ewfd.Ez)","imag(ewfd.Ez)","ewfd.Poavx","ewfd.Poavy"});
    for(int k=1;k<=2;k++)field(m,d,"MODE"+k,"p"+k,new String[]{"PortName","c_const/freq/1[nm]","x/1[um]","y/1[um]","real(ewfd.tEmodez_"+k+")","imag(ewfd.tEmodez_"+k+")","real(ewfd.tHmodey_"+k+")","imag(ewfd.tHmodey_"+k+")"});
    marker("NATIVE_COMPLETED");
  }
  static void sequence(Model m){
    m.study("std").createAutoSequences("sol");
    for(String s:m.sol().tags()){
      marker("AUTO_SEQUENCE "+s+" study="+m.sol(s).study()+" features="+Arrays.toString(m.sol(s).feature().tags()));
      for(String f:m.sol(s).feature().tags()){
        marker("AUTO_FEATURE "+s+"/"+f+" type="+m.sol(s).feature(f).getType());
        if("StudyStep".equals(m.sol(s).feature(f).getType()))for(String p:m.sol(s).feature(f).properties()){
          try{marker("AUTO_STEP_PROPERTY "+s+"/"+f+" "+p+"="+m.sol(s).feature(f).getString(p));}catch(Exception ex){marker("AUTO_PROPERTY_NONSCALAR "+s+"/"+f+" "+p);}
        }
      }
    }
  }
  public static Model run()throws Exception{
    marker("STAGE "+STAGE+" SHAPE "+SHAPE);
    if(STAGE.equals("solve")){Model m=ModelUtil.load("Canary","input_modes.mph");m.modelPath(".");resumeDriven(m);return m;}
    Model m=build();sequence(m);m.save("configured.mph");
    if(STAGE.equals("modes"))modes(m);else marker("CONFIGURATION_COMPLETED");return m;
  }
  public static void main(String[] args)throws Exception{run();}
}
